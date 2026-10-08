"""Uçtan uca akış (API üzerinden, sentetik veri):
takip Excel'i → site → tarife → açılış bakiyesi → tahakkuk → ekstre (dedup) → inceleme → öğrenme → raporlar.
"""

from datetime import date
from decimal import Decimal

from tests.factories import sample_bank_rows, tracking_excel, ziraat_statement

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def upload(client, url, data: bytes, name="dosya.xlsx", **form):
    return client.post(url, files={"file": (name, data, XLSX)}, data={k: str(v) for k, v in form.items() if v is not None})


def setup_site(client) -> int:
    excel = tracking_excel()
    r = upload(client, "/api/imports/tracking/preview", excel, site_name="DENEME KONAKLARI", cutoff="2026-01")
    assert r.status_code == 200, r.text
    prev = r.json()
    assert prev["unit_count"] == 12 and prev["start_year"] == 2025 and prev["cutoff"] == "2026-01"
    assert [b["name"] for b in prev["blocks"]] == ["A1", "B", "C2"]

    r = upload(client, "/api/imports/tracking/commit", excel, "takip.xlsx", site_name="DENEME KONAKLARI", cutoff="2026-01")
    assert r.status_code == 200, r.text
    site_id = r.json()["site_id"]
    assert r.json()["legacy_payments"] > 0

    site = client.get(f"/api/sites/{site_id}").json()
    blocks = {b["name"]: b["id"] for b in site["blocks"]}
    assert client.patch(f"/api/blocks/{blocks['B']}", json={"aliases": ["b1", "b2"]}).status_code == 200
    assert client.patch(f"/api/blocks/{blocks['C2']}", json={"aliases": ["5/2c"]}).status_code == 200
    for amount, start in ((3000, "2025-07"), (3500, "2026-01")):
        r = client.post(f"/api/sites/{site_id}/tariffs", json={"amount": amount, "valid_from": start})
        assert r.status_code == 201, r.text
    tariffs = client.get(f"/api/sites/{site_id}/tariffs").json()
    assert {t["valid_from"]: t["valid_to"] for t in tariffs} == {"2026-01": None, "2025-07": "2025-12"}
    return site_id


def unit_ids(client, site_id) -> dict[str, int]:
    return {u["code"]: u["id"] for u in client.get(f"/api/sites/{site_id}/units").json()}


def test_full_flow(client):
    site_id = setup_site(client)
    units = unit_ids(client, site_id)

    # --- Açılış bakiyesi ---
    sug = client.get(f"/api/sites/{site_id}/opening/tariff-suggestions").json()
    assert sug["periods"][0]["amount"] == "3000.00"
    comp = client.get(f"/api/sites/{site_id}/opening/compute", params={"cutoff": "2026-01"}).json()
    rows = {r["code"]: r for r in comp["rows"]}
    assert rows["A1-1"]["computed_balance"] == "0.00"
    # A1-3: başlangıç = site başlangıcı (ilk ödeme değil); 2025-07..12 tahakkuk (6x3000), Temmuz ve Kasım ödenmemiş
    assert rows["A1-3"]["start_period"] == "2025-07"
    assert rows["A1-3"]["first_payment_period"] == "2025-08"
    assert rows["A1-3"]["computed_balance"] == "6000.00"
    r = client.post(f"/api/sites/{site_id}/opening/approve", json={
        "cutoff": "2026-01", "rows": [{"unit_id": units["A1-3"], "approved_balance": "2500", "note": "indirim"}]})
    assert r.status_code == 200, r.text
    assert r.json() == {"locked_until": "2025-12", "adjustments": 1}

    # --- Ocak-Şubat tahakkukları ---
    r = client.post(f"/api/sites/{site_id}/charges/generate", json={"start": "2026-01", "end": "2026-02"})
    assert r.status_code == 200 and r.json()[0]["created"] == 12
    r = client.post(f"/api/sites/{site_id}/charges/generate", json={"start": "2026-01"})
    assert r.json()[0]["created"] == 0  # idempotent

    # --- Ekstre ---
    bank = ziraat_statement(sample_bank_rows())
    r = upload(client, "/api/imports/bank", bank, "ekstre1.xlsx")
    assert r.status_code == 409 and r.json()["code"] == "unknown_iban"
    r = upload(client, "/api/imports/bank", bank, "ekstre1.xlsx", site_id=site_id)
    assert r.status_code == 200, r.text
    res = r.json()
    assert (res["new"], res["duplicates"]) == (12, 0)
    assert (res["auto_matched"], res["suggested"], res["unmatched"]) == (10, 1, 1), res
    assert res["footer_credit_total"] == res["credit_total"]
    assert res["gaps"] == []

    # Aynı dosya tekrar -> hiçbir şey eklenmez
    r = upload(client, "/api/imports/bank", bank, "ekstre1-kopya.xlsx")
    assert r.json()["already_imported"] is True and r.json()["new"] == 0
    # Kısa aralıklı (çakışan) ekstre -> 0 yeni
    cropped = ziraat_statement(sample_bank_rows(), skip_before=date(2026, 1, 10))
    r = upload(client, "/api/imports/bank", cropped, "ekstre-kisa.xlsx")
    assert (r.json()["new"], r.json()["duplicates"]) == (0, 6)

    txns = client.get(f"/api/sites/{site_id}/transactions", params={"page_size": 100}).json()["items"]
    by_receipt = {t["receipt_no"]: t for t in txns}
    expect_auto = {"F00001": "A1-1", "F00002": "B-1", "F00003": "C2-2", "F00004": "C2-4", "F00005": "A1-4",
                   "F00007": "A1-2", "F00009": "A1-3", "F00010": "B-4", "F00011": "C2-1", "F00012": "B-3"}
    for rec, code in expect_auto.items():
        t = by_receipt[rec]
        assert t["status"] == "matched", (rec, t["reasons"], t["candidates"])
        assert [a["code"] for a in t["allocations"]] == [code], rec
    assert by_receipt["F00011"]["allocations"][0]["category"] == "demirbas"
    assert by_receipt["F00001"]["allocations"][0]["period"] == "2026-01"  # gönderildiği ay

    split_txn = by_receipt["F00006"]
    assert split_txn["status"] == "suggested"
    assert {units_code for units_code in (c["code"] for c in split_txn["candidates"])} >= {"A1-4", "B-4"}
    assert [s["amount"] for s in split_txn["split"]] == ["3500.00", "3500.00"]
    assert by_receipt["F00008"]["status"] == "unmatched"

    # --- İnceleme: bölüştürmeyi onayla (hafızaya al), tanımsızı yok say ---
    r = client.post(f"/api/transactions/{split_txn['id']}/confirm", json={
        "allocations": [{"unit_id": units["A1-4"], "amount": "3500"}, {"unit_id": units["B-4"], "amount": "3500"}],
        "remember": True})
    assert r.status_code == 200 and r.json()["status"] == "matched"
    r = client.post(f"/api/transactions/{by_receipt['F00008']['id']}/confirm",
                    json={"allocations": [{"unit_id": units["A1-1"], "amount": "9999"}]})
    assert r.status_code == 400  # işlem tutarını aşamaz
    r = client.post(f"/api/transactions/{by_receipt['F00008']['id']}/ignore", json={"note": "iade edilecek"})
    assert r.json()["status"] == "ignored"

    aliases = {a["normalized_name"]: a for a in client.get(f"/api/sites/{site_id}/aliases").json()}
    assert aliases["john smith"]["mode"] == "split"
    assert aliases["baska biri"]["targets"][0]["code"] == "A1-2"  # kod ile otomatik öğrenildi

    # --- İkinci ekstre: öğrenilen gönderenler artık kod yazmadan eşleşir ---
    D = Decimal
    more = sample_bank_rows() + [
        (date(2026, 2, 6), "F00013", "Monthly payment JOHN SMITH Ziraat Mobil Havale", D(7000)),
        (date(2026, 2, 7), "F00014", "Gönd: BAŞKA BİRİ aidat 0012-Türkiye Halk Bankası A.Ş. FAST işlemi", D(3500)),
        (date(2025, 12, 30), "F00015", "Gönd: ALİ VELİ A1 blok daire 1 0205-Kuveyt", D(3000)),
    ]
    more.sort(key=lambda r: r[0])
    # 30 Aralık'taki +3000 ile bakiye 10000'e ulaşır -> eski satırların bakiyeleri birebir aynı kalır
    r = upload(client, "/api/imports/bank", ziraat_statement(more, opening=D("7000.00")), "ekstre2.xlsx")
    res2 = r.json()
    assert (res2["new"], res2["duplicates"]) == (3, 12), res2
    assert res2["gaps"] == []
    # Bakiyesi farklı hesaplanmış bir dışa aktarım: fiş no + tarih + tutar aynı olduğu için yine tekrar sayılır
    r = upload(client, "/api/imports/bank", ziraat_statement(more, opening=D("1.00")), "ekstre2-farkli-bakiye.xlsx")
    assert r.json()["new"] == 0
    txns = client.get(f"/api/sites/{site_id}/transactions", params={"page_size": 200}).json()["items"]
    assert len(txns) == 15
    new = {t["receipt_no"]: t for t in txns if t["receipt_no"] in ("F00013", "F00014", "F00015")}
    assert sorted(a["code"] for a in new["F00013"]["allocations"]) == ["A1-4", "B-4"]
    assert [a["code"] for a in new["F00014"]["allocations"]] == ["A1-2"]
    assert new["F00015"]["status"] == "ignored" and "Kesim" in new["F00015"]["note"]
    assert res2["before_cutoff"] == 1

    # --- Raporlar ---
    grid = client.get(f"/api/sites/{site_id}/grid", params={"start": "2025-07", "end": "2026-02"}).json()
    a11 = next(u for b in grid["blocks"] for u in b["units"] if u["code"] == "A1-1")
    assert a11["cells"]["2026-01"]["status"] in ("paid", "extra")
    debt = {d["code"]: d for d in client.get(f"/api/sites/{site_id}/debtors").json()}
    assert debt["A1-3"]["overdue_months"] >= 1
    st = client.get(f"/api/units/{units['A1-3']}/statement").json()
    assert any(e["type"] == "duzeltme" and Decimal(str(e["debit"])) == Decimal("-3500") for e in st["entries"])
    rec = client.get(f"/api/sites/{site_id}/reconciliation").json()
    assert rec["available"] and rec["cutoff"] == "2026-01"
    dash = client.get(f"/api/sites/{site_id}/dashboard", params={"period": "2026-01"}).json()
    assert dash["unit_count"] == 12 and Decimal(dash["charged_this_month"]) == Decimal("42000.00")
    for url in (f"/api/sites/{site_id}/export/grid.xlsx?start=2025-07&end=2026-02",
                f"/api/sites/{site_id}/export/debtors.xlsx", f"/api/units/{units['A1-3']}/export/statement.xlsx"):
        r = client.get(url)
        assert r.status_code == 200 and r.headers["content-type"] == XLSX and r.content[:2] == b"PK"

    # --- Dönem kilidi: operatör kilitli döneme tahakkuk ekleyemez ---
    r = client.post("/api/users", json={"email": "op@test.local", "password": "op123", "role": "operator", "site_ids": [site_id]})
    assert r.status_code == 201
    op = client.post("/api/auth/login", data={"username": "op@test.local", "password": "op123"}).json()["access_token"]
    r = client.post(f"/api/sites/{site_id}/charges", headers={"Authorization": f"Bearer {op}"},
                    json={"unit_id": units["A1-1"], "period": "2025-10", "amount": "100", "description": "deneme"})
    assert r.status_code == 409
    assert client.get(f"/api/sites/{site_id}/audit").json()


def test_site_wizard_and_manual_payment(client):
    r = client.post("/api/sites", json={
        "name": "Yeni Site", "aidat_start_period": "2026-01", "ibans": ["TR33 0006 1005 1978 6457 8413 26"],
        "blocks": [{"name": "A", "unit_count": 3, "room_type": "2+1"}, {"name": "B", "unit_count": 2, "room_type": "3+1"}],
        "default_amount": "1000", "room_type_tariffs": [{"room_type": "3+1", "amount": "1500"}]})
    assert r.status_code == 201, r.text
    site = r.json()
    assert site["bank_accounts"][0]["iban"] == "TR330006100519786457841326"
    sid = site["id"]
    r = client.post(f"/api/sites/{sid}/charges/generate", json={"start": "2026-01"})
    assert r.json()[0]["created"] == 5
    units = unit_ids(client, sid)
    charges = {c["code"]: Decimal(str(c["amount"])) for c in client.get(f"/api/sites/{sid}/charges").json()}
    assert charges["A-1"] == Decimal("1000") and charges["B-1"] == Decimal("1500")
    r = client.post(f"/api/sites/{sid}/transactions/manual", json={
        "txn_date": "2026-01-15", "amount": "1000", "unit_id": units["A-1"], "description": "elden ödeme"})
    assert r.status_code == 201 and r.json()["status"] == "matched"
    debt = {d["code"]: d for d in client.get(f"/api/sites/{sid}/debtors").json()}
    assert Decimal(debt["A-1"]["balance"]) == 0 and Decimal(debt["B-1"]["balance"]) == Decimal("1500")
    r = client.post(f"/api/sites/{sid}/tariffs/increase", json={"valid_from": "2026-07", "percent": "25"})
    assert sorted(Decimal(str(t["amount"])) for t in r.json()) == [Decimal("1250"), Decimal("1900")]
