"""Açılış bakiyesi sihirbazı.

1) Eski ödemelerden tarife geçmişi önerilir (dönem bazında en sık tutar).
2) Kesim dönemine kadar tahakkuk − ödeme ile her dairenin bakiyesi hesaplanır.
3) Yönetici düzenler ve onaylar: geçmiş tahakkuklar yazılır, fark 'düzeltme' olarak kaydedilir, dönem kilitlenir.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Charge, PaymentAllocation, PeriodLock, Site
from app.services.common import add_months, money, period_range
from app.services.ledger import LedgerError, site_units, tariff_resolver_for_site, unit_start_period

MIN_SAMPLES = 3


def _mode(values: list[Decimal]) -> tuple[Decimal | None, int]:
    if not values:
        return None, 0
    (val, cnt), = Counter(values).most_common(1)
    return val, cnt


def suggest_tariffs(db: Session, site_id: int, cutoff: str | None = None) -> dict:
    site = db.get(Site, site_id)
    cutoff = cutoff or site.legacy_cutoff_period
    q = select(PaymentAllocation.unit_id, PaymentAllocation.period, PaymentAllocation.amount).where(
        PaymentAllocation.site_id == site_id, PaymentAllocation.category == "aidat"
    )
    if cutoff:
        q = q.where(PaymentAllocation.period < cutoff)
    by_period: dict[str, list[Decimal]] = defaultdict(list)
    by_unit_period: dict[int, dict[str, Decimal]] = defaultdict(dict)
    for unit_id, period, amount in db.execute(q):
        a = Decimal(amount)
        by_period[period].append(a)
        by_unit_period[unit_id][period] = by_unit_period[unit_id].get(period, Decimal(0)) + a
    if not by_period:
        return {"periods": [], "unit_deviations": []}

    # Dönem bazında en sık tutar; az örnekli dönemler bir öncekini devralır
    periods = period_range(min(by_period), max(by_period))
    modes: list[tuple[str, Decimal | None, int]] = []
    last: Decimal | None = None
    for p in periods:
        val, cnt = _mode(by_period.get(p, []))
        if cnt >= MIN_SAMPLES:
            last = val
        modes.append((p, last, cnt))

    ranges: list[dict] = []
    for p, val, cnt in modes:
        if val is None:
            continue
        if ranges and ranges[-1]["amount"] == str(val):
            ranges[-1]["valid_to"] = p
            ranges[-1]["sample_size"] += cnt
        else:
            ranges.append({"valid_from": p, "valid_to": p, "amount": str(val), "sample_size": cnt})
    if ranges:
        ranges[-1]["valid_to"] = None  # son dönem açık uçlu

    # Site tarifesinden sistematik olarak farklı ödeyen daireler (oda tipi farkı olabilir)
    units = {u.id: u for u in site_units(db, site_id)}
    deviations: list[dict] = []
    for r in ranges:
        rng = period_range(r["valid_from"], r["valid_to"] or max(by_period))
        for uid, pays in by_unit_period.items():
            vals = [pays[p] for p in rng if p in pays]
            val, cnt = _mode(vals)
            if cnt >= MIN_SAMPLES and str(val) != r["amount"]:
                deviations.append({"unit_id": uid, "code": units[uid].code if uid in units else str(uid),
                                   "valid_from": r["valid_from"], "valid_to": r["valid_to"],
                                   "typical_amount": str(val), "site_amount": r["amount"], "samples": cnt})
    return {"periods": ranges, "unit_deviations": deviations}


def suggest_unit_starts(db: Session, site_id: int) -> dict[int, str]:
    rows = db.execute(
        select(PaymentAllocation.unit_id, func.min(PaymentAllocation.period))
        .where(PaymentAllocation.site_id == site_id).group_by(PaymentAllocation.unit_id)
    )
    return {uid: p for uid, p in rows}


def compute_opening(db: Session, site_id: int, cutoff: str | None = None) -> dict:
    site = db.get(Site, site_id)
    cutoff = cutoff or site.legacy_cutoff_period
    if not cutoff:
        raise LedgerError("Kesim dönemi belirtilmeli")
    last = add_months(cutoff, -1)
    resolve = tariff_resolver_for_site(db, site_id)
    starts = suggest_unit_starts(db, site_id)

    paid = dict(db.execute(
        select(PaymentAllocation.unit_id, func.sum(PaymentAllocation.amount))
        .where(PaymentAllocation.site_id == site_id, PaymentAllocation.period < cutoff).group_by(PaymentAllocation.unit_id)
    ).all())
    other_charges = dict(db.execute(
        select(Charge.unit_id, func.sum(Charge.amount))
        .where(Charge.site_id == site_id, Charge.period < cutoff, Charge.source != "opening", Charge.type != "aidat")
        .group_by(Charge.unit_id)
    ).all())

    rows = []
    for u in site_units(db, site_id):
        start = unit_start_period(u, site) or starts.get(u.id)
        months = period_range(start, last) if start and start <= last else []
        aidat_total = Decimal(0)
        missing: list[str] = []
        for p in months:
            amt = resolve(u.id, p)
            if amt is None:
                missing.append(p)
            else:
                aidat_total += amt
        extra = Decimal(other_charges.get(u.id) or 0)
        payments = Decimal(paid.get(u.id) or 0)
        computed = aidat_total + extra - payments
        rows.append({
            "unit_id": u.id, "code": u.code, "start_period": start, "first_payment_period": starts.get(u.id),
            "start_is_explicit": bool(u.aidat_start_period), "months": len(months),
            "aidat_total": str(money(aidat_total)), "other_charges": str(money(extra)), "payments": str(money(payments)),
            "computed_balance": str(money(computed)), "missing_tariff_periods": missing[:12],
            "missing_tariff_count": len(missing),
        })
    lock = db.scalar(select(PeriodLock).where(PeriodLock.site_id == site_id))
    return {"cutoff": cutoff, "last_period": last, "rows": rows, "locked_until": lock.locked_until if lock else None}


def approve_opening(db: Session, site_id: int, cutoff: str, rows: list[dict], *, user_id: int | None, is_admin: bool) -> dict:
    """rows: [{"unit_id", "approved_balance", "note"}]. Listede olmayan daireler hesaplanan bakiyeyle onaylanır."""
    lock = db.scalar(select(PeriodLock).where(PeriodLock.site_id == site_id))
    if lock and not is_admin:
        raise LedgerError("Açılış bakiyesi zaten onaylanmış; yeniden onay için yönetici yetkisi gerekir")

    computed = {r["unit_id"]: r for r in compute_opening(db, site_id, cutoff)["rows"]}
    overrides = {int(r["unit_id"]): r for r in rows}
    site = db.get(Site, site_id)
    resolve = tariff_resolver_for_site(db, site_id)
    last = add_months(cutoff, -1)

    db.execute(delete(Charge).where(Charge.site_id == site_id, Charge.source == "opening"))
    db.flush()
    existing_keys = set(db.scalars(select(Charge.unique_key).where(Charge.site_id == site_id, Charge.unique_key.is_not(None))))

    adjustments = 0
    for u in site_units(db, site_id):
        c = computed[u.id]
        start = c["start_period"]
        if start and not u.aidat_start_period:
            u.aidat_start_period = start
        has_history = c["months"] > 0 or Decimal(c["payments"]) != 0
        if start and start <= last:
            for p in period_range(start, last):
                key = f"aidat:{u.id}:{p}"
                amt = resolve(u.id, p)
                if amt is None or key in existing_keys:
                    continue
                db.add(Charge(site_id=site_id, unit_id=u.id, period=p, type="aidat", amount=amt,
                              description=f"{p} aidatı (açılış)", source="opening", unique_key=key, created_by=user_id))
        ov = overrides.get(u.id)
        if ov is not None and ov.get("approved_balance") not in (None, ""):
            diff = money(ov["approved_balance"]) - money(c["computed_balance"])
            if diff != 0:
                db.add(Charge(
                    site_id=site_id, unit_id=u.id, period=last, type="duzeltme" if has_history else "devir", amount=diff,
                    description=(ov.get("note") or "Açılış bakiyesi düzeltmesi") if has_history else (ov.get("note") or "Devir bakiyesi"),
                    source="opening", created_by=user_id,
                ))
                adjustments += 1
    if lock:
        lock.locked_until = last
        lock.revision = (lock.revision or 1) + 1
        lock.created_by = user_id
    else:
        db.add(PeriodLock(site_id=site_id, locked_until=last, created_by=user_id))
    site.legacy_cutoff_period = site.legacy_cutoff_period or cutoff
    db.add(AuditLog(user_id=user_id, site_id=site_id, action="approve_opening", entity="site", entity_id=site_id,
                    data={"cutoff": cutoff, "adjustments": adjustments}))
    db.flush()
    return {"locked_until": last, "adjustments": adjustments}
