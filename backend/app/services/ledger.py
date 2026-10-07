"""Tarife çözümleme, tahakkuk üretimi, bakiye ve borç yaşlandırma.

Bakiye = Σ tahakkuk − Σ dağıtılan ödeme (pozitif = borç, negatif = alacak/avans).
Ödemeler gönderildiği aya yazılır; "kaç ay borçlu" bilgisi sanal FIFO ile sadece gösterim için hesaplanır.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Block, Charge, ChargeBatch, PaymentAllocation, PeriodLock, Site, Tariff, Unit
from app.services.common import period_range


class LedgerError(Exception):
    pass


# --- Tarife ---------------------------------------------------------------------------


def site_units(db: Session, site_id: int) -> list[Unit]:
    return list(
        db.scalars(
            select(Unit).join(Block).where(Block.site_id == site_id).options(selectinload(Unit.block))
            .order_by(Block.sort_order, Block.name, Unit.number)
        )
    )


def make_tariff_resolver(tariffs: list[Tariff], units: list[Unit]) -> Callable[[int, str], Decimal | None]:
    room_type = {u.id: u.room_type for u in units}
    by_scope: dict[str, list[Tariff]] = defaultdict(list)
    for t in tariffs:
        by_scope[t.scope].append(t)
    for lst in by_scope.values():
        lst.sort(key=lambda t: t.valid_from, reverse=True)

    def active(t: Tariff, period: str) -> bool:
        return t.valid_from <= period and (t.valid_to is None or period <= t.valid_to)

    cache: dict[tuple[int, str], Decimal | None] = {}

    def resolve(unit_id: int, period: str) -> Decimal | None:
        key = (unit_id, period)
        if key in cache:
            return cache[key]
        result = None
        for t in by_scope.get("unit", []):
            if t.scope_value == str(unit_id) and active(t, period):
                result = t.amount
                break
        if result is None and room_type.get(unit_id):
            for t in by_scope.get("room_type", []):
                if t.scope_value == room_type[unit_id] and active(t, period):
                    result = t.amount
                    break
        if result is None:
            for t in by_scope.get("site", []):
                if active(t, period):
                    result = t.amount
                    break
        cache[key] = result
        return result

    return resolve


def tariff_resolver_for_site(db: Session, site_id: int) -> Callable[[int, str], Decimal | None]:
    tariffs = list(db.scalars(select(Tariff).where(Tariff.site_id == site_id)))
    return make_tariff_resolver(tariffs, site_units(db, site_id))


# --- Dönem kilidi -----------------------------------------------------------------------


def locked_until(db: Session, site_id: int) -> str | None:
    lock = db.scalar(select(PeriodLock).where(PeriodLock.site_id == site_id))
    return lock.locked_until if lock else None


def ensure_unlocked(db: Session, site_id: int, period: str, *, is_admin: bool = False) -> None:
    lu = locked_until(db, site_id)
    if lu and period <= lu and not is_admin:
        raise LedgerError(f"{period} dönemi kilitli (açılış bakiyesi onaylandı: {lu} ve öncesi). Sadece yönetici değiştirebilir.")


# --- Tahakkuk ---------------------------------------------------------------------------


def unit_start_period(unit: Unit, site: Site) -> str | None:
    return unit.aidat_start_period or site.aidat_start_period


def generate_monthly_charges(
    db: Session, site_id: int, period: str, *, user_id: int | None = None, source: str = "auto", is_admin: bool = False
) -> dict:
    """Ayın aidat tahakkuklarını üretir. İdempotent: aynı daire+ay ikinci kez oluşturulmaz."""
    ensure_unlocked(db, site_id, period, is_admin=is_admin)
    site = db.get(Site, site_id)
    units = site_units(db, site_id)
    resolve = tariff_resolver_for_site(db, site_id)
    existing = set(
        db.scalars(select(Charge.unique_key).where(Charge.site_id == site_id, Charge.period == period, Charge.type == "aidat"))
    )
    created = skipped_no_tariff = skipped_not_started = 0
    for u in units:
        start = unit_start_period(u, site)
        if start and period < start:
            skipped_not_started += 1
            continue
        key = f"aidat:{u.id}:{period}"
        if key in existing:
            continue
        amount = resolve(u.id, period)
        if amount is None:
            skipped_no_tariff += 1
            continue
        db.add(Charge(site_id=site_id, unit_id=u.id, period=period, type="aidat", amount=amount,
                      description=f"{period} aidatı", source=source, unique_key=key, created_by=user_id))
        created += 1
    db.flush()
    return {"period": period, "created": created, "already_exists": len(existing),
            "skipped_no_tariff": skipped_no_tariff, "skipped_not_started": skipped_not_started}


def create_charge_batch(
    db: Session, site_id: int, *, type: str, period: str, amount: Decimal, description: str,
    unit_ids: list[int] | None = None, user_id: int | None = None, is_admin: bool = False,
) -> ChargeBatch:
    ensure_unlocked(db, site_id, period, is_admin=is_admin)
    batch = ChargeBatch(site_id=site_id, type=type, period=period, amount=amount, description=description, created_by=user_id)
    db.add(batch)
    db.flush()
    units = site_units(db, site_id)
    targets = [u for u in units if unit_ids is None or u.id in set(unit_ids)]
    for u in targets:
        db.add(Charge(site_id=site_id, unit_id=u.id, period=period, type=type, amount=amount, description=description,
                      source="batch", batch_id=batch.id, created_by=user_id))
    db.flush()
    return batch


# --- Bakiye ----------------------------------------------------------------------------


@dataclass
class UnitBalance:
    unit_id: int
    charged: Decimal
    paid: Decimal
    balance: Decimal
    overdue_months: int
    oldest_unpaid_period: str | None


def _fifo_overdue(charges: list[tuple[str, Decimal]], paid: Decimal) -> tuple[int, str | None]:
    remaining = paid
    unpaid_periods: list[str] = []
    for period, amount in sorted(charges):
        if amount <= 0:
            remaining += -amount
            continue
        if remaining >= amount:
            remaining -= amount
        else:
            remaining = Decimal(0)
            unpaid_periods.append(period)
    distinct = sorted(set(unpaid_periods))
    return len(distinct), (distinct[0] if distinct else None)


def site_balances(db: Session, site_id: int, upto_period: str | None = None) -> dict[int, UnitBalance]:
    cq = select(Charge.unit_id, Charge.period, Charge.amount).where(Charge.site_id == site_id)
    pq = select(PaymentAllocation.unit_id, func.sum(PaymentAllocation.amount)).where(PaymentAllocation.site_id == site_id)
    if upto_period:
        cq = cq.where(Charge.period <= upto_period)
        pq = pq.where(PaymentAllocation.period <= upto_period)
    charges: dict[int, list[tuple[str, Decimal]]] = defaultdict(list)
    for unit_id, period, amount in db.execute(cq):
        charges[unit_id].append((period, Decimal(amount)))
    paid = {uid: Decimal(s or 0) for uid, s in db.execute(pq.group_by(PaymentAllocation.unit_id))}
    out: dict[int, UnitBalance] = {}
    for u in site_units(db, site_id):
        ch = charges.get(u.id, [])
        total_c = sum((a for _, a in ch), Decimal(0))
        total_p = paid.get(u.id, Decimal(0))
        months, oldest = _fifo_overdue(ch, total_p)
        out[u.id] = UnitBalance(u.id, total_c, total_p, total_c - total_p, months, oldest)
    return out


def unit_statement(db: Session, unit_id: int) -> list[dict]:
    """Daire hesap ekstresi: tahakkuk ve ödemeler tarih sırasıyla, yürüyen bakiye."""
    from app.models import BankTransaction

    entries: list[dict] = []
    for c in db.scalars(select(Charge).where(Charge.unit_id == unit_id)):
        entries.append({"kind": "charge", "id": c.id, "period": c.period, "date": f"{c.period}-01", "type": c.type,
                        "description": c.description or c.type, "debit": c.amount, "credit": Decimal(0), "source": c.source})
    rows = db.execute(
        select(PaymentAllocation, BankTransaction)
        .join(BankTransaction, BankTransaction.id == PaymentAllocation.transaction_id)
        .where(PaymentAllocation.unit_id == unit_id)
    )
    for a, t in rows:
        entries.append({"kind": "payment", "id": a.id, "transaction_id": t.id, "period": a.period, "date": t.txn_date.isoformat(),
                        "type": a.category, "description": t.description, "debit": Decimal(0), "credit": a.amount,
                        "source": t.source, "method": a.method})
    # Aynı gün içinde önce tahakkuk sonra ödeme
    entries.sort(key=lambda e: (e["date"], 0 if e["kind"] == "charge" else 1, e["id"]))
    running = Decimal(0)
    for e in entries:
        running += e["debit"] - e["credit"]
        e["balance"] = running
    return entries


def periods_between(start: str, end: str) -> list[str]:
    return period_range(start, end)
