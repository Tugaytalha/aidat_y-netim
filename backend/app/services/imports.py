"""Banka ekstresi ve takip Excel'i içe aktarma."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    BankAccount, BankTransaction, Block, ImportBatch, PaymentAllocation, Person, Site, Unit, UnitOccupancy,
)
from app.services.bank_parsers import ParsedStatement, parse_statement
from app.services.common import add_months, period_of
from app.services.dedup import ChainRow, dedup_key, find_gaps
from app.services.legacy_import.tracking_excel import TrackingParse, parse_tracking_excel
from app.services.matching.normalize import normalize_name
from app.services.matching.service import run_matching


class ImportError_(Exception):
    pass


class UnknownIbanError(ImportError_):
    def __init__(self, statement: ParsedStatement):
        self.statement = statement
        super().__init__(f"Bu IBAN ({statement.iban}) hiçbir siteye tanımlı değil. Hangi siteye ait olduğunu seçin.")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- Banka ekstresi -------------------------------------------------------------------


def account_gaps(db: Session, bank_account_id: int) -> list[dict]:
    rows = db.execute(
        select(BankTransaction.txn_date, BankTransaction.seq, BankTransaction.amount, BankTransaction.balance_after)
        .where(BankTransaction.bank_account_id == bank_account_id, BankTransaction.source == "bank")
    )
    return find_gaps([ChainRow(d, s, Decimal(a), Decimal(b) if b is not None else None) for d, s, a, b in rows])


def account_coverage(db: Session, bank_account_id: int) -> list[dict]:
    batches = db.scalars(
        select(ImportBatch).where(ImportBatch.bank_account_id == bank_account_id, ImportBatch.kind == "bank_statement")
        .order_by(ImportBatch.period_start)
    )
    return [{"import_id": b.id, "file_name": b.file_name, "start": b.period_start, "end": b.period_end} for b in batches]


def import_bank_statement(db: Session, data: bytes, file_name: str, *, user_id: int | None, site_id: int | None = None) -> dict:
    digest = sha256(data)
    st = parse_statement(data)
    if not st.iban:
        raise ImportError_("Ekstrede IBAN bulunamadı")

    account = db.scalar(select(BankAccount).where(BankAccount.iban == st.iban))
    if account is None:
        if site_id is None:
            raise UnknownIbanError(st)
        account = BankAccount(site_id=site_id, iban=st.iban, bank_name=st.bank_name, account_no=st.account_no)
        db.add(account)
        db.flush()
    elif site_id is not None and account.site_id != site_id:
        raise ImportError_(f"Bu IBAN başka bir siteye ({account.site.name}) tanımlı")
    site = db.get(Site, account.site_id)

    previous = db.scalar(
        select(ImportBatch).where(ImportBatch.file_sha256 == digest, ImportBatch.kind == "bank_statement",
                                  ImportBatch.site_id == site.id)
    )
    if previous is not None:
        # Birebir aynı dosya: satırları tekrar işlemeye gerek yok
        return {"import_id": previous.id, "site_id": site.id, "bank_account_id": account.id, "iban": st.iban,
                "period_start": st.period_start, "period_end": st.period_end, "already_imported": True,
                **{**(previous.stats or {}), "new": 0, "duplicates": len(st.transactions)}}

    batch = ImportBatch(
        site_id=site.id, kind="bank_statement", bank_account_id=account.id, file_name=file_name, file_sha256=digest,
        bank_code=st.bank_code, period_start=st.period_start, period_end=st.period_end, uploaded_by=user_id,
    )
    db.add(batch)
    db.flush()

    keys = [dedup_key(st.iban, t) for t in st.transactions]
    existing: set[str] = set()
    for i in range(0, len(keys), 500):
        existing |= set(db.scalars(select(BankTransaction.dedup_key).where(BankTransaction.dedup_key.in_(keys[i : i + 500]))))

    # İkinci kontrol: fiş numarası olan satırlarda (tarih, fiş, tutar) aynıysa bakiye farklı olsa da tekrardır
    soft_existing: set[tuple] = set()
    if st.transactions:
        dates = [t.txn_date for t in st.transactions]
        for d, rec, amt in db.execute(
            select(BankTransaction.txn_date, BankTransaction.receipt_no, BankTransaction.amount).where(
                BankTransaction.bank_account_id == account.id, BankTransaction.source == "bank",
                BankTransaction.receipt_no.is_not(None), BankTransaction.txn_date >= min(dates),
                BankTransaction.txn_date <= max(dates))
        ):
            soft_existing.add((d, rec, Decimal(amt)))

    new_txns: list[BankTransaction] = []
    seen_in_file: set[str] = set()
    before_cutoff = 0
    for t, key in zip(st.transactions, keys):
        if key in existing or key in seen_in_file:
            continue
        if t.receipt_no and (t.txn_date, t.receipt_no, t.amount) in soft_existing:
            continue
        seen_in_file.add(key)
        txn = BankTransaction(
            site_id=site.id, bank_account_id=account.id, import_id=batch.id, source="bank", txn_date=t.txn_date,
            seq=t.seq, receipt_no=t.receipt_no, description=t.description, amount=t.amount,
            balance_after=t.balance_after, direction="in" if t.amount > 0 else "out", dedup_key=key, status="unmatched",
        )
        if site.legacy_cutoff_period and period_of(t.txn_date) < site.legacy_cutoff_period:
            txn.status = "ignored"
            txn.note = f"Kesim dönemi ({site.legacy_cutoff_period}) öncesi: takip Excel'inde kayıtlı"
            before_cutoff += 1
        db.add(txn)
        new_txns.append(txn)
    db.flush()

    to_match = [t for t in new_txns if t.status == "unmatched"]
    match_stats = run_matching(db, site.id, to_match) if to_match else {"auto": 0, "suggest": 0, "none": 0, "ignored": 0}

    credits = sum((t.amount for t in st.transactions if t.amount > 0), Decimal(0))
    gaps = account_gaps(db, account.id)
    stats = {
        "total_rows": len(st.transactions),
        "new": len(new_txns),
        "duplicates": len(st.transactions) - len(new_txns),
        "before_cutoff": before_cutoff,
        "auto_matched": match_stats["auto"],
        "suggested": match_stats["suggest"],
        "unmatched": match_stats["none"],
        "outgoing_ignored": match_stats["ignored"],
        "credit_total": str(credits),
        "footer_credit_total": str(st.footer_credit_total) if st.footer_credit_total is not None else None,
        "warnings": st.warnings,
        "gaps": gaps,
    }
    batch.stats = stats
    db.flush()
    return {"import_id": batch.id, "site_id": site.id, "bank_account_id": account.id, "iban": st.iban,
            "period_start": st.period_start, "period_end": st.period_end, "already_imported": False, **stats}


# --- Takip Excel'i ---------------------------------------------------------------------


def _default_cutoff(db: Session, site_id: int | None, tp: TrackingParse) -> str:
    if site_id:
        first_bank = db.scalar(
            select(BankTransaction.txn_date).where(BankTransaction.site_id == site_id, BankTransaction.source == "bank")
            .order_by(BankTransaction.txn_date).limit(1)
        )
        if first_bank:
            return period_of(first_bank)
    return add_months(period_of(date.today()), 0)


def preview_tracking(
    db: Session, data: bytes, *, site_id: int | None, site_name: str | None, start_year: int | None,
    cutoff: str | None, sheet: str | None = None,
) -> dict:
    name = site_name or (db.get(Site, site_id).name if site_id else None)
    tp = parse_tracking_excel(data, sheet=sheet, site_name=name, start_year=start_year)
    cutoff = cutoff or _default_cutoff(db, site_id, tp)
    units = []
    legacy_total = post_total = Decimal(0)
    for u in tp.units:
        before = {p: a for p, a in u.payments.items() if p < cutoff}
        after = {p: a for p, a in u.payments.items() if p >= cutoff}
        legacy_total += sum(before.values(), Decimal(0))
        post_total += sum(after.values(), Decimal(0))
        units.append({
            "block": u.block, "number": u.number, "code": f"{u.block}-{u.number}", "raw_name": u.raw_name,
            "names": u.names, "payment_count": len(u.payments), "legacy_total": str(sum(before.values(), Decimal(0))),
            "post_cutoff_total": str(sum(after.values(), Decimal(0))), "first_period": min(u.payments) if u.payments else None,
            "one_offs": {k: str(v) for k, v in u.one_offs.items()}, "tags": u.tags,
            "expressions": u.raw_cells,
        })
    return {
        "sheet": tp.sheet, "start_year": tp.start_year, "first_period": tp.first_period, "last_period": tp.last_period,
        "cutoff": cutoff, "blocks": [{"name": b, "unit_count": sum(1 for u in tp.units if u.block == b)} for b in tp.block_order],
        "unit_count": len(tp.units), "units": units, "legacy_total": str(legacy_total), "post_cutoff_total": str(post_total),
        "warnings": tp.warnings, "notes": tp.notes,
    }


def _person_for(db: Session, site_id: int, name: str, cache: dict[str, Person]) -> Person:
    key = normalize_name(name)
    if key in cache:
        return cache[key]
    p = db.scalar(select(Person).where(Person.site_id == site_id, Person.normalized_name == key))
    if p is None:
        p = Person(site_id=site_id, full_name=name.strip(), normalized_name=key)
        db.add(p)
        db.flush()
    cache[key] = p
    return p


def commit_tracking(
    db: Session, data: bytes, file_name: str, *, user_id: int | None, site_id: int | None, site_name: str | None,
    site_code: str | None, start_year: int | None, cutoff: str | None, sheet: str | None = None,
) -> dict:
    name = site_name or (db.get(Site, site_id).name if site_id else None)
    if not name:
        raise ImportError_("Yeni site için ad gerekli")
    tp = parse_tracking_excel(data, sheet=sheet, site_name=name, start_year=start_year)
    cutoff = cutoff or _default_cutoff(db, site_id, tp)

    if site_id is None:
        code = site_code or normalize_name(name).replace(" ", "-")[:40] or "site"
        if db.scalar(select(Site).where(Site.code == code)):
            raise ImportError_(f"'{code}' kodlu site zaten var")
        site = Site(name=name, code=code)
        db.add(site)
        db.flush()
    else:
        site = db.get(Site, site_id)
        # Önceki takip Excel'i içe aktarımlarını (ve onların eski ödemelerini) kaldır
        for old in db.scalars(select(ImportBatch).where(ImportBatch.site_id == site.id, ImportBatch.kind == "tracking_excel")):
            old_txn_ids = list(db.scalars(select(BankTransaction.id).where(BankTransaction.import_id == old.id)))
            if old_txn_ids:
                db.execute(delete(PaymentAllocation).where(PaymentAllocation.transaction_id.in_(old_txn_ids)))
                db.execute(delete(BankTransaction).where(BankTransaction.id.in_(old_txn_ids)))
            db.delete(old)
        db.flush()

    site.legacy_cutoff_period = cutoff
    if not site.aidat_start_period:
        site.aidat_start_period = tp.first_period

    blocks = {b.name: b for b in db.scalars(select(Block).where(Block.site_id == site.id))}
    for i, bname in enumerate(tp.block_order):
        if bname not in blocks:
            blocks[bname] = Block(site_id=site.id, name=bname, aliases=[], sort_order=i)
            db.add(blocks[bname])
    db.flush()

    batch = ImportBatch(site_id=site.id, kind="tracking_excel", file_name=file_name, file_sha256=sha256(data),
                        uploaded_by=user_id)
    db.add(batch)
    db.flush()

    person_cache: dict[str, Person] = {}
    post_cutoff: dict[str, dict[str, str]] = {}
    one_offs: dict[str, dict[str, str]] = {}
    legacy_count = 0
    created_units = 0
    for u in tp.units:
        block = blocks[u.block]
        unit = db.scalar(select(Unit).where(Unit.block_id == block.id, Unit.number == u.number))
        if unit is None:
            unit = Unit(block_id=block.id, number=u.number, legacy_tags={})
            db.add(unit)
            created_units += 1
        # Daire başlangıcı bilinçli olarak boş bırakılır: varsayılan site başlangıcıdır. "İlk ödeme ayı"
        # başlangıç sayılırsa hiç/ geç ödeyenlerin eski borcu görünmez olur (açılış sihirbazında düzenlenir).
        unit.legacy_tags = {**(unit.legacy_tags or {}), **u.tags, "excel_name": u.raw_name}
        db.flush()

        existing_people = {o.person_id for o in db.scalars(select(UnitOccupancy).where(UnitOccupancy.unit_id == unit.id))}
        for idx, n in enumerate(u.names):
            p = _person_for(db, site.id, n, person_cache)
            if p.id in existing_people:
                continue
            is_last = idx == len(u.names) - 1
            db.add(UnitOccupancy(unit_id=unit.id, person_id=p.id, role="owner" if is_last else "former", is_primary=is_last))
            existing_people.add(p.id)

        for period, amount in sorted(u.payments.items()):
            if period >= cutoff:
                post_cutoff.setdefault(str(unit.id), {})[period] = str(amount)
                continue
            raw = u.raw_cells.get(period)
            key = sha256(f"legacy|{site.id}|{unit.id}|{period}".encode())
            txn = BankTransaction(
                site_id=site.id, import_id=batch.id, source="legacy_excel", txn_date=date.fromisoformat(f"{period}-01"),
                seq=0, description=f"Takip Excel'i: {block.name}-{u.number} {period}" + (f" ({raw})" if raw else ""),
                amount=amount, direction="in", dedup_key=key, status="matched", payer_name=u.names[-1] if u.names else None,
                category_hint="aidat",
            )
            db.add(txn)
            db.flush()
            db.add(PaymentAllocation(transaction_id=txn.id, site_id=site.id, unit_id=unit.id, amount=amount,
                                     category="aidat", period=period, method="legacy", confidence=1.0))
            legacy_count += 1
        if u.one_offs:
            one_offs[str(unit.id)] = {k: str(v) for k, v in u.one_offs.items()}

    batch.period_start = date.fromisoformat(f"{tp.first_period}-01")
    batch.period_end = date.fromisoformat(f"{add_months(cutoff, -1)}-01")
    batch.payload = {"cutoff": cutoff, "post_cutoff": post_cutoff, "one_offs": one_offs, "notes": tp.notes,
                     "start_year": tp.start_year, "sheet": tp.sheet}
    batch.stats = {"units": len(tp.units), "created_units": created_units, "legacy_payments": legacy_count,
                   "persons": len(person_cache), "warnings": tp.warnings}

    # Kesimden önceye düşen ve daha önce yüklenmiş banka işlemleri artık çift sayım olur -> yok say
    for t in db.scalars(select(BankTransaction).where(BankTransaction.site_id == site.id, BankTransaction.source == "bank")):
        if period_of(t.txn_date) < cutoff and t.status != "ignored":
            for a in list(t.allocations):
                db.delete(a)
            t.status = "ignored"
            t.note = f"Kesim dönemi ({cutoff}) öncesi: takip Excel'inde kayıtlı"
    db.flush()
    return {"import_id": batch.id, "site_id": site.id, "cutoff": cutoff, **batch.stats}
