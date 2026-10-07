from datetime import date
from decimal import Decimal

from app.services.bank_parsers import parse_statement
from app.services.common import parse_amount_expression, parse_tr_number
from app.services.dedup import ChainRow, dedup_key, find_gaps
from app.services.legacy_import.tracking_excel import parse_tracking_excel, split_names
from app.services.xlsx.reader import _read_raw_xml, read_workbook
from tests.factories import IBAN, sample_bank_rows, tracking_excel, ziraat_statement


def test_tr_numbers():
    assert parse_tr_number("1.086.785") == Decimal("1086785.00")
    assert parse_tr_number("3.500,50") == Decimal("3500.50")
    assert parse_tr_number(3600.0) == Decimal("3600.00")
    assert parse_tr_number("1.15") == Decimal("1.15")
    assert parse_amount_expression("3600+70.000") == Decimal("73600.00")
    assert parse_amount_expression("2000+1000") == Decimal("3000.00")
    assert parse_amount_expression("Numarası yok") is None


def test_ziraat_parser_synthetic():
    st = parse_statement(ziraat_statement(sample_bank_rows()))
    assert st.bank_code == "ziraat"
    assert st.iban == IBAN
    assert st.account_holder == "DENEME KONAKLARI SİTE YÖNETİMİ"
    assert st.period_start == date(2026, 1, 5) and st.period_end == date(2026, 2, 4)
    assert len(st.transactions) == 12
    assert st.footer_credit_total == sum(t.amount for t in st.transactions)
    assert not st.warnings
    # Aynı gün iki işlem: kronolojik sıra dosyadaki ters sıradan çıkarılır
    same_day = sorted((t for t in st.transactions if t.txn_date == date(2026, 1, 8)), key=lambda t: t.seq)
    assert [t.receipt_no for t in same_day] == ["F00004", "F00005"]


def test_raw_xml_reader_matches_calamine():
    data = ziraat_statement(sample_bank_rows())
    a = read_workbook(data)
    b = _read_raw_xml(data)
    sheet = "Hesap hareketleri"
    assert [r[:5] for r in a[sheet]][7] == [r[:5] for r in b[sheet]][7]


def test_dedup_keys_stable_and_unique():
    st = parse_statement(ziraat_statement(sample_bank_rows()))
    keys = [dedup_key(st.iban, t) for t in st.transactions]
    assert len(set(keys)) == len(keys)
    st2 = parse_statement(ziraat_statement(sample_bank_rows()))
    assert keys == [dedup_key(st2.iban, t) for t in st2.transactions]


def test_gap_detection():
    D = Decimal
    rows = [
        ChainRow(date(2026, 1, 1), 1, D(100), D(1100)),
        ChainRow(date(2026, 1, 1), 2, D(50), D(1150)),
        ChainRow(date(2026, 1, 3), 1, D(100), D(1250)),
        # 5 Ocak: arada 500'lük bir hareket eksik
        ChainRow(date(2026, 1, 10), 1, D(100), D(1850)),
    ]
    gaps = find_gaps(rows)
    assert len(gaps) == 1
    assert gaps[0]["after"] == "2026-01-03" and gaps[0]["before"] == "2026-01-10"
    assert find_gaps(rows[:3]) == []


def test_tracking_parser_synthetic():
    tp = parse_tracking_excel(tracking_excel(), site_name="DENEME KONAKLARI", reference=date(2026, 12, 15))
    assert tp.block_order == ["A1", "B", "C2"]
    assert tp.start_year == 2025
    assert tp.first_period == "2025-07" and tp.last_period == "2026-12"
    assert len(tp.units) == 12
    u = next(u for u in tp.units if u.block == "B" and u.number == 2)
    assert u.payments["2025-12"] == Decimal("4500.00")
    assert u.raw_cells["2025-12"] == "3000+1500"
    a3 = next(u for u in tp.units if u.block == "A1" and u.number == 3)
    assert a3.names == ["zeynep ak"]  # site adı yer tutucusu ("DENEME") atlandı
    a4 = next(u for u in tp.units if u.block == "A1" and u.number == 4)
    assert a4.tags["A"] == "T B"
    assert a4.one_offs == {}
    assert "işlenmeyen" in " ".join(tp.notes)


def test_split_names():
    assert split_names("AYLA KAR / MEHMET ALİ TAŞ") == ["AYLA KAR", "MEHMET ALİ TAŞ"]
    assert split_names("OMAR AHMD TESTLI- Kemal") == ["OMAR AHMD TESTLI", "Kemal"]
    assert split_names("GÜLFA  - deniz ak", "GÜLFA MAMİK KONAKLARI") == ["deniz ak"]
    assert split_names("CAN TOPRAK-Ece toprak") == ["CAN TOPRAK", "Ece toprak"]
