"""Tarife, tahakkuk ve açılış bakiyesi uç noktaları."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, Writer, audit, get_site
from app.models import Charge, Tariff, Unit
from app.services import ledger, opening_balance
from app.services.common import add_months, period_range
from app.services.ledger import LedgerError

router = APIRouter(prefix="/api", tags=["ledger"])
PERIOD_RE = r"^\d{4}-(0[1-9]|1[0-2])$"


def tariff_out(t: Tariff, unit_codes: dict[int, str] | None = None) -> dict:
    label = "Tüm site"
    if t.scope == "room_type":
        label = f"Oda tipi: {t.scope_value}"
    elif t.scope == "unit":
        label = f"Daire: {(unit_codes or {}).get(int(t.scope_value), t.scope_value)}"
    return {"id": t.id, "scope": t.scope, "scope_value": t.scope_value, "scope_label": label, "amount": t.amount,
            "valid_from": t.valid_from, "valid_to": t.valid_to, "note": t.note}


@router.get("/sites/{site_id}/tariffs")
def list_tariffs(site_id: int, db: DB, user: CurrentUser):
    get_site(db, user, site_id)
    codes = {u.id: u.code for u in ledger.site_units(db, site_id)}
    q = select(Tariff).where(Tariff.site_id == site_id).order_by(Tariff.valid_from.desc(), Tariff.scope)
    return [tariff_out(t, codes) for t in db.scalars(q)]


class TariffIn(BaseModel):
    scope: str = "site"
    scope_value: str | None = None
    amount: Decimal = Field(gt=0)
    valid_from: str = Field(pattern=PERIOD_RE)
    valid_to: str | None = Field(default=None, pattern=PERIOD_RE)
    note: str | None = None


@router.post("/sites/{site_id}/tariffs", status_code=201)
def create_tariff(site_id: int, body: TariffIn, db: DB, user: Writer):
    get_site(db, user, site_id)
    if body.scope not in ("site", "room_type", "unit"):
        raise HTTPException(400, "Geçersiz kapsam")
    if body.scope != "site" and not body.scope_value:
        raise HTTPException(400, "Oda tipi ya da daire seçilmeli")
    # Aynı kapsamdaki açık uçlu önceki tarifeyi yeni başlangıçtan bir ay önce kapat
    for prev in db.scalars(select(Tariff).where(Tariff.site_id == site_id, Tariff.scope == body.scope,
                                                Tariff.scope_value == body.scope_value, Tariff.valid_to.is_(None),
                                                Tariff.valid_from < body.valid_from)):
        prev.valid_to = add_months(body.valid_from, -1)
    t = Tariff(site_id=site_id, **body.model_dump())
    db.add(t)
    audit(db, user, "create", "tariff", None, site_id, {k: str(v) for k, v in body.model_dump().items()})
    db.commit()
    return tariff_out(t)


@router.patch("/tariffs/{tariff_id}")
def update_tariff(tariff_id: int, body: TariffIn, db: DB, user: Writer):
    t = db.get(Tariff, tariff_id)
    if not t:
        raise HTTPException(404, "Tarife bulunamadı")
    get_site(db, user, t.site_id)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    audit(db, user, "update", "tariff", t.id, t.site_id, {k: str(v) for k, v in body.model_dump().items()})
    db.commit()
    return tariff_out(t)


@router.delete("/tariffs/{tariff_id}", status_code=204)
def delete_tariff(tariff_id: int, db: DB, user: Writer):
    t = db.get(Tariff, tariff_id)
    if not t:
        raise HTTPException(404, "Tarife bulunamadı")
    get_site(db, user, t.site_id)
    audit(db, user, "delete", "tariff", t.id, t.site_id, {"amount": str(t.amount), "valid_from": t.valid_from})
    db.delete(t)
    db.commit()


class IncreaseIn(BaseModel):
    valid_from: str = Field(pattern=PERIOD_RE)
    percent: Decimal | None = None
    amount_delta: Decimal | None = None
    round_to: int = 50


@router.post("/sites/{site_id}/tariffs/increase")
def increase_tariffs(site_id: int, body: IncreaseIn, db: DB, user: Writer):
    """Toplu artış: o tarihte geçerli tüm tarifeleri yüzde ya da tutar olarak artırır."""
    get_site(db, user, site_id)
    if body.percent is None and body.amount_delta is None:
        raise HTTPException(400, "Yüzde ya da tutar girin")
    current = [t for t in db.scalars(select(Tariff).where(Tariff.site_id == site_id))
               if t.valid_from < body.valid_from and (t.valid_to is None or t.valid_to >= body.valid_from)]
    created = []
    for t in current:
        new_amount = t.amount * (1 + (body.percent or 0) / 100) + (body.amount_delta or 0)
        if body.round_to:
            new_amount = (new_amount / body.round_to).quantize(Decimal(1), rounding=ROUND_HALF_UP) * body.round_to
        t.valid_to = add_months(body.valid_from, -1)
        nt = Tariff(site_id=site_id, scope=t.scope, scope_value=t.scope_value, amount=new_amount,
                    valid_from=body.valid_from, note=f"Toplu artış ({body.percent or ''}% {body.amount_delta or ''})")
        db.add(nt)
        created.append(nt)
    audit(db, user, "increase", "tariff", None, site_id, {k: str(v) for k, v in body.model_dump().items()})
    db.commit()
    return [tariff_out(t) for t in created]


# --- Tahakkuk --------------------------------------------------------------------------


class GenerateIn(BaseModel):
    start: str = Field(pattern=PERIOD_RE)
    end: str | None = Field(default=None, pattern=PERIOD_RE)


@router.post("/sites/{site_id}/charges/generate")
def generate_charges(site_id: int, body: GenerateIn, db: DB, user: Writer):
    get_site(db, user, site_id)
    results = []
    try:
        for p in period_range(body.start, body.end or body.start):
            results.append(ledger.generate_monthly_charges(db, site_id, p, user_id=user.id, is_admin=user.role == "admin"))
    except LedgerError as e:
        db.rollback()
        raise HTTPException(409, str(e)) from e
    audit(db, user, "generate", "charge", None, site_id, {"start": body.start, "end": body.end})
    db.commit()
    return results


class BatchIn(BaseModel):
    type: str
    period: str = Field(pattern=PERIOD_RE)
    amount: Decimal = Field(gt=0)
    description: str = Field(min_length=3)
    unit_ids: list[int] | None = None


@router.post("/sites/{site_id}/charge-batches", status_code=201)
def create_batch(site_id: int, body: BatchIn, db: DB, user: Writer):
    get_site(db, user, site_id)
    if body.type not in ("demirbas", "asansor", "ek_butce", "aidat"):
        raise HTTPException(400, "Geçersiz tür")
    try:
        b = ledger.create_charge_batch(db, site_id, type=body.type, period=body.period, amount=body.amount,
                                       description=body.description, unit_ids=body.unit_ids, user_id=user.id,
                                       is_admin=user.role == "admin")
    except LedgerError as e:
        db.rollback()
        raise HTTPException(409, str(e)) from e
    audit(db, user, "create", "charge_batch", b.id, site_id, {"type": body.type, "amount": str(body.amount)})
    db.commit()
    return {"id": b.id}


@router.get("/sites/{site_id}/charges")
def list_charges(site_id: int, db: DB, user: CurrentUser, unit_id: int | None = None, period: str | None = None,
                 type: str | None = None, limit: int = 500):
    get_site(db, user, site_id)
    q = select(Charge).where(Charge.site_id == site_id)
    if unit_id:
        q = q.where(Charge.unit_id == unit_id)
    if period:
        q = q.where(Charge.period == period)
    if type:
        q = q.where(Charge.type == type)
    q = q.order_by(Charge.period.desc(), Charge.id.desc()).limit(min(limit, 5000))
    return [{"id": c.id, "unit_id": c.unit_id, "code": c.unit.code, "period": c.period, "type": c.type,
             "amount": c.amount, "description": c.description, "source": c.source} for c in db.scalars(q)]


class ManualChargeIn(BaseModel):
    unit_id: int
    period: str = Field(pattern=PERIOD_RE)
    type: str = "duzeltme"
    amount: Decimal
    description: str = Field(min_length=3)


@router.post("/sites/{site_id}/charges", status_code=201)
def create_manual_charge(site_id: int, body: ManualChargeIn, db: DB, user: Writer):
    get_site(db, user, site_id)
    unit = db.get(Unit, body.unit_id)
    if not unit or unit.block.site_id != site_id:
        raise HTTPException(400, "Daire bulunamadı")
    try:
        ledger.ensure_unlocked(db, site_id, body.period, is_admin=user.role == "admin")
    except LedgerError as e:
        raise HTTPException(409, str(e)) from e
    c = Charge(site_id=site_id, unit_id=body.unit_id, period=body.period, type=body.type, amount=body.amount,
               description=body.description, source="manual", created_by=user.id)
    db.add(c)
    db.flush()
    audit(db, user, "create", "charge", c.id, site_id, {k: str(v) for k, v in body.model_dump().items()})
    db.commit()
    return {"id": c.id}


@router.delete("/charges/{charge_id}", status_code=204)
def delete_charge(charge_id: int, db: DB, user: Writer):
    c = db.get(Charge, charge_id)
    if not c:
        raise HTTPException(404, "Tahakkuk bulunamadı")
    get_site(db, user, c.site_id)
    try:
        ledger.ensure_unlocked(db, c.site_id, c.period, is_admin=user.role == "admin")
    except LedgerError as e:
        raise HTTPException(409, str(e)) from e
    audit(db, user, "delete", "charge", c.id, c.site_id, {"unit_id": c.unit_id, "period": c.period, "amount": str(c.amount)})
    db.delete(c)
    db.commit()


# --- Açılış bakiyesi -------------------------------------------------------------------


@router.get("/sites/{site_id}/opening/tariff-suggestions")
def tariff_suggestions(site_id: int, db: DB, user: CurrentUser, cutoff: str | None = None):
    get_site(db, user, site_id)
    return opening_balance.suggest_tariffs(db, site_id, cutoff)


@router.get("/sites/{site_id}/opening/compute")
def opening_compute(site_id: int, db: DB, user: CurrentUser, cutoff: str | None = None):
    get_site(db, user, site_id)
    try:
        return opening_balance.compute_opening(db, site_id, cutoff)
    except LedgerError as e:
        raise HTTPException(400, str(e)) from e


class OpeningRow(BaseModel):
    unit_id: int
    approved_balance: Decimal | None = None
    note: str | None = None


class OpeningApproveIn(BaseModel):
    cutoff: str = Field(pattern=PERIOD_RE)
    rows: list[OpeningRow] = []


@router.post("/sites/{site_id}/opening/approve")
def opening_approve(site_id: int, body: OpeningApproveIn, db: DB, user: Writer):
    get_site(db, user, site_id)
    try:
        result = opening_balance.approve_opening(
            db, site_id, body.cutoff, [r.model_dump() for r in body.rows], user_id=user.id, is_admin=user.role == "admin"
        )
    except LedgerError as e:
        db.rollback()
        raise HTTPException(409, str(e)) from e
    db.commit()
    return result
