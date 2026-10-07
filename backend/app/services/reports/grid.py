"""Tahsilat çizelgesi (daireler × aylar), borçlu listesi, mutabakat ve pano verileri."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BankAccount, BankTransaction, Charge, ImportBatch, PaymentAllocation, Person, Site, UnitOccupancy
from app.services.common import add_months, money, period_of, period_range
from app.services.imports import account_gaps
from app.services.ledger import site_balances, site_units


def _names_by_unit(db: Session, site_id: int) -> dict[int, list[str]]:
    rows = db.execute(
        select(UnitOccupancy.unit_id, Person.full_name, UnitOccupancy.is_primary)
        .join(Person, Person.id == UnitOccupancy.person_id).where(Person.site_id == site_id)
        .order_by(UnitOccupancy.is_primary.desc(), UnitOccupancy.id)
    )
    out: dict[int, list[str]] = defaultdict(list)
    for uid, name, _ in rows:
        out[uid].append(name)
    return out


def payment_grid(db: Session, site_id: int, start: str, end: str) -> dict:
    periods = period_range(start, end)
    paid: dict[tuple[int, str], Decimal] = defaultdict(Decimal)
    for uid, period, amount in db.execute(
        select(PaymentAllocation.unit_id, PaymentAllocation.period, func.sum(PaymentAllocation.amount))
        .where(PaymentAllocation.site_id == site_id, PaymentAllocation.period >= start, PaymentAllocation.period <= end)
        .group_by(PaymentAllocation.unit_id, PaymentAllocation.period)
    ):
        paid[(uid, period)] = Decimal(amount)
    charged: dict[tuple[int, str], Decimal] = defaultdict(Decimal)
    for uid, period, amount in db.execute(
        select(Charge.unit_id, Charge.period, func.sum(Charge.amount))
        .where(Charge.site_id == site_id, Charge.period >= start, Charge.period <= end)
        .group_by(Charge.unit_id, Charge.period)
    ):
        charged[(uid, period)] = Decimal(amount)
    balances = site_balances(db, site_id)
    names = _names_by_unit(db, site_id)

    blocks: dict[str, list[dict]] = {}
    for u in site_units(db, site_id):
        cells = {}
        for p in periods:
            pv, cv = paid.get((u.id, p)), charged.get((u.id, p))
            if pv is None and cv is None:
                continue
            pv = pv or Decimal(0)
            cv = cv or Decimal(0)
            status = "paid" if cv > 0 and pv >= cv else "partial" if pv > 0 and cv > pv else "unpaid" if cv > 0 else "extra"
            cells[p] = {"paid": str(money(pv)), "charged": str(money(cv)), "status": status}
        b = balances[u.id]
        blocks.setdefault(u.block.name, []).append({
            "unit_id": u.id, "code": u.code, "number": u.number, "names": names.get(u.id, []), "room_type": u.room_type,
            "cells": cells, "balance": str(money(b.balance)), "overdue_months": b.overdue_months,
        })
    totals = {p: str(money(sum((paid.get((u, p), Decimal(0)) for u, _p in paid if _p == p), Decimal(0))))
              for p in periods}
    return {"periods": periods, "blocks": [{"name": k, "units": v} for k, v in blocks.items()], "totals": totals}


def debtors(db: Session, site_id: int) -> list[dict]:
    balances = site_balances(db, site_id)
    names = _names_by_unit(db, site_id)
    out = []
    for u in site_units(db, site_id):
        b = balances[u.id]
        bucket = "yok" if b.overdue_months == 0 else "1 ay" if b.overdue_months == 1 else "2-3 ay" if b.overdue_months <= 3 else "3+ ay"
        out.append({
            "unit_id": u.id, "code": u.code, "names": names.get(u.id, []), "charged": str(money(b.charged)),
            "paid": str(money(b.paid)), "balance": str(money(b.balance)), "overdue_months": b.overdue_months,
            "oldest_unpaid_period": b.oldest_unpaid_period, "bucket": bucket,
        })
    out.sort(key=lambda r: -Decimal(r["balance"]))
    return out


def reconciliation(db: Session, site_id: int) -> dict:
    """Takip Excel'inin kesim sonrası sütunları ↔ sistemde o dönemlere yazılan ödemeler."""
    batch = db.scalar(
        select(ImportBatch).where(ImportBatch.site_id == site_id, ImportBatch.kind == "tracking_excel")
        .order_by(ImportBatch.id.desc())
    )
    if not batch:
        return {"available": False, "rows": []}
    post = batch.payload.get("post_cutoff", {})
    cutoff = batch.payload.get("cutoff")
    sys_paid: dict[tuple[int, str], Decimal] = defaultdict(Decimal)
    for uid, period, amount in db.execute(
        select(PaymentAllocation.unit_id, PaymentAllocation.period, func.sum(PaymentAllocation.amount))
        .where(PaymentAllocation.site_id == site_id, PaymentAllocation.period >= cutoff)
        .group_by(PaymentAllocation.unit_id, PaymentAllocation.period)
    ):
        sys_paid[(uid, period)] = Decimal(amount)
    units = {u.id: u for u in site_units(db, site_id)}
    rows = []
    keys = {(int(uid), p) for uid, ps in post.items() for p in ps} | set(sys_paid)
    excel_total = sys_total = Decimal(0)
    for uid, p in sorted(keys, key=lambda k: (units[k[0]].code if k[0] in units else "", k[1])):
        ev = Decimal(post.get(str(uid), {}).get(p, "0"))
        sv = sys_paid.get((uid, p), Decimal(0))
        excel_total += ev
        sys_total += sv
        if ev != sv:
            rows.append({"unit_id": uid, "code": units[uid].code if uid in units else str(uid), "period": p,
                         "excel": str(ev), "system": str(sv), "diff": str(sv - ev)})
    # Daire bazında toplam (ay etiketinden bağımsız) farklar
    per_unit: dict[int, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for (uid, p) in keys:
        per_unit[uid][0] += Decimal(post.get(str(uid), {}).get(p, "0"))
        per_unit[uid][1] += sys_paid.get((uid, p), Decimal(0))
    unit_rows = [
        {"unit_id": uid, "code": units[uid].code if uid in units else str(uid), "excel": str(e), "system": str(s), "diff": str(s - e)}
        for uid, (e, s) in sorted(per_unit.items(), key=lambda kv: units[kv[0]].code if kv[0] in units else "") if e != s
    ]
    return {"available": True, "cutoff": cutoff, "rows": rows, "unit_rows": unit_rows,
            "excel_total": str(excel_total), "system_total": str(sys_total)}


def dashboard(db: Session, site_id: int, period: str | None = None) -> dict:
    from datetime import date

    period = period or period_of(date.today())
    site = db.get(Site, site_id)
    charged = Decimal(db.scalar(select(func.coalesce(func.sum(Charge.amount), 0)).where(
        Charge.site_id == site_id, Charge.period == period, Charge.type == "aidat")) or 0)
    collected = Decimal(db.scalar(select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
        PaymentAllocation.site_id == site_id, PaymentAllocation.period == period)) or 0)
    balances = site_balances(db, site_id)
    receivable = sum((b.balance for b in balances.values() if b.balance > 0), Decimal(0))
    advance = -sum((b.balance for b in balances.values() if b.balance < 0), Decimal(0))
    status_counts = dict(db.execute(
        select(BankTransaction.status, func.count()).where(BankTransaction.site_id == site_id, BankTransaction.source == "bank")
        .group_by(BankTransaction.status)
    ).all())
    last_txn = db.scalar(select(func.max(BankTransaction.txn_date)).where(
        BankTransaction.site_id == site_id, BankTransaction.source == "bank"))
    last_import = db.scalar(select(ImportBatch).where(ImportBatch.site_id == site_id).order_by(ImportBatch.id.desc()))
    gaps = []
    for acc in db.scalars(select(BankAccount).where(BankAccount.site_id == site_id)):
        gaps += account_gaps(db, acc.id)
    debtor_count = sum(1 for b in balances.values() if b.overdue_months > 0)
    monthly = []
    for p in period_range(add_months(period, -11), period):
        c = Decimal(db.scalar(select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
            PaymentAllocation.site_id == site_id, PaymentAllocation.period == p)) or 0)
        monthly.append({"period": p, "collected": str(money(c))})
    return {
        "site": {"id": site.id, "name": site.name}, "period": period,
        "charged_this_month": str(money(charged)), "collected_this_month": str(money(collected)),
        "collection_rate": float(round(collected / charged, 4)) if charged else None,
        "total_receivable": str(money(receivable)), "total_advance": str(money(advance)),
        "debtor_units": debtor_count, "unit_count": len(balances),
        "transactions": {k: v for k, v in status_counts.items()},
        "needs_review": status_counts.get("suggested", 0) + status_counts.get("unmatched", 0),
        "last_transaction_date": last_txn.isoformat() if last_txn else None,
        "last_import": {"file_name": last_import.file_name, "at": last_import.uploaded_at.isoformat(), "kind": last_import.kind}
        if last_import else None,
        "gaps": gaps, "monthly": monthly,
    }
