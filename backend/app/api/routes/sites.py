from __future__ import annotations

import re
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, Writer, accessible_site_ids, audit, get_site
from app.models import BankAccount, Block, PayerAlias, Site, Tariff, Unit, UnitOccupancy
from app.services.ledger import site_balances, site_units

router = APIRouter(prefix="/api", tags=["sites"])

PERIOD_RE = r"^\d{4}-(0[1-9]|1[0-2])$"


def site_out(s: Site, with_children: bool = False) -> dict:
    d = {"id": s.id, "name": s.name, "code": s.code, "address": s.address, "aidat_start_period": s.aidat_start_period,
         "legacy_cutoff_period": s.legacy_cutoff_period, "llm_enabled": s.llm_enabled,
         "auto_match_threshold": s.auto_match_threshold, "notes": s.notes}
    if with_children:
        d["bank_accounts"] = [{"id": a.id, "iban": a.iban, "bank_name": a.bank_name, "account_no": a.account_no,
                               "branch": a.branch} for a in s.bank_accounts]
        d["blocks"] = [block_out(b) for b in s.blocks]
    return d


def block_out(b: Block) -> dict:
    return {"id": b.id, "name": b.name, "aliases": b.aliases or [], "sort_order": b.sort_order,
            "units": [{"id": u.id, "number": u.number, "code": u.code, "room_type": u.room_type,
                       "area_m2": float(u.area_m2) if u.area_m2 is not None else None,
                       "aidat_start_period": u.aidat_start_period} for u in b.units]}


@router.get("/sites")
def list_sites(db: DB, user: CurrentUser):
    allowed = accessible_site_ids(db, user)
    q = select(Site).order_by(Site.name)
    sites = [s for s in db.scalars(q) if allowed is None or s.id in allowed]
    out = []
    for s in sites:
        unit_count = len(site_units(db, s.id))
        out.append({**site_out(s), "unit_count": unit_count})
    return out


class BlockIn(BaseModel):
    name: str
    unit_count: int = Field(ge=1, le=500)
    aliases: list[str] = []
    room_type: str | None = None


class RoomTariffIn(BaseModel):
    room_type: str
    amount: Decimal


class SiteIn(BaseModel):
    name: str
    code: str | None = None
    address: str | None = None
    aidat_start_period: str | None = Field(default=None, pattern=PERIOD_RE)
    ibans: list[str] = []
    blocks: list[BlockIn] = []
    default_amount: Decimal | None = None
    room_type_tariffs: list[RoomTariffIn] = []
    tariff_valid_from: str | None = Field(default=None, pattern=PERIOD_RE)


def _slug(name: str) -> str:
    from app.services.matching.normalize import normalize_name

    return re.sub(r"\s+", "-", normalize_name(name))[:40] or "site"


@router.post("/sites", status_code=201)
def create_site(body: SiteIn, db: DB, user: Writer):
    code = body.code or _slug(body.name)
    if db.scalar(select(Site).where(Site.code == code)):
        raise HTTPException(409, f"'{code}' kodlu site zaten var")
    site = Site(name=body.name.strip(), code=code, address=body.address, aidat_start_period=body.aidat_start_period)
    db.add(site)
    db.flush()
    for iban in body.ibans:
        iban = iban.replace(" ", "").upper()
        if not iban:
            continue
        if db.scalar(select(BankAccount).where(BankAccount.iban == iban)):
            raise HTTPException(409, f"{iban} başka bir siteye tanımlı")
        db.add(BankAccount(site_id=site.id, iban=iban))
    for i, b in enumerate(body.blocks):
        name = b.name.strip().upper().replace(" ", "")
        block = Block(site_id=site.id, name=name, aliases=[a.strip() for a in b.aliases if a.strip()], sort_order=i)
        db.add(block)
        db.flush()
        for n in range(1, b.unit_count + 1):
            db.add(Unit(block_id=block.id, number=n, room_type=b.room_type, legacy_tags={}))
    valid_from = body.tariff_valid_from or body.aidat_start_period
    if (body.default_amount or body.room_type_tariffs) and not valid_from:
        raise HTTPException(400, "Tarife için geçerlilik başlangıcı (ay) gerekli")
    if body.default_amount:
        db.add(Tariff(site_id=site.id, scope="site", amount=body.default_amount, valid_from=valid_from))
    for rt in body.room_type_tariffs:
        db.add(Tariff(site_id=site.id, scope="room_type", scope_value=rt.room_type, amount=rt.amount, valid_from=valid_from))
    audit(db, user, "create", "site", site.id, site.id, {"name": site.name})
    db.commit()
    db.refresh(site)
    return site_out(site, with_children=True)


@router.get("/sites/{site_id}")
def get_site_detail(site_id: int, db: DB, user: CurrentUser):
    site = get_site(db, user, site_id)
    db.refresh(site)
    return site_out(site, with_children=True)


class SitePatch(BaseModel):
    name: str | None = None
    address: str | None = None
    aidat_start_period: str | None = Field(default=None, pattern=PERIOD_RE)
    legacy_cutoff_period: str | None = Field(default=None, pattern=PERIOD_RE)
    llm_enabled: bool | None = None
    auto_match_threshold: float | None = Field(default=None, ge=0.5, le=1.0)
    notes: str | None = None


@router.patch("/sites/{site_id}")
def update_site(site_id: int, body: SitePatch, db: DB, user: Writer):
    site = get_site(db, user, site_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(site, k, v)
    audit(db, user, "update", "site", site.id, site.id, data)
    db.commit()
    return site_out(site, with_children=True)


# --- Bloklar ---------------------------------------------------------------------------


class BlockCreate(BaseModel):
    name: str
    unit_count: int = Field(ge=1, le=500)
    aliases: list[str] = []


@router.post("/sites/{site_id}/blocks", status_code=201)
def add_block(site_id: int, body: BlockCreate, db: DB, user: Writer):
    get_site(db, user, site_id)
    name = body.name.strip().upper().replace(" ", "")
    if db.scalar(select(Block).where(Block.site_id == site_id, Block.name == name)):
        raise HTTPException(409, "Bu adla blok var")
    order = len(list(db.scalars(select(Block.id).where(Block.site_id == site_id))))
    b = Block(site_id=site_id, name=name, aliases=body.aliases, sort_order=order)
    db.add(b)
    db.flush()
    for n in range(1, body.unit_count + 1):
        db.add(Unit(block_id=b.id, number=n, legacy_tags={}))
    audit(db, user, "create", "block", b.id, site_id, {"name": name})
    db.commit()
    db.refresh(b)
    return block_out(b)


class BlockPatch(BaseModel):
    name: str | None = None
    aliases: list[str] | None = None
    sort_order: int | None = None
    add_units: int | None = Field(default=None, ge=1, le=100)


@router.patch("/blocks/{block_id}")
def update_block(block_id: int, body: BlockPatch, db: DB, user: Writer):
    b = db.get(Block, block_id)
    if not b:
        raise HTTPException(404, "Blok bulunamadı")
    get_site(db, user, b.site_id)
    if body.name is not None:
        b.name = body.name.strip().upper().replace(" ", "")
    if body.aliases is not None:
        b.aliases = [a.strip() for a in body.aliases if a.strip()]
    if body.sort_order is not None:
        b.sort_order = body.sort_order
    if body.add_units:
        start = max((u.number for u in b.units), default=0)
        for n in range(start + 1, start + body.add_units + 1):
            db.add(Unit(block_id=b.id, number=n, legacy_tags={}))
    audit(db, user, "update", "block", b.id, b.site_id, body.model_dump(exclude_none=True))
    db.commit()
    db.refresh(b)
    return block_out(b)


# --- Daireler --------------------------------------------------------------------------


@router.get("/sites/{site_id}/units")
def list_units(site_id: int, db: DB, user: CurrentUser):
    get_site(db, user, site_id)
    balances = site_balances(db, site_id)
    occ = db.scalars(
        select(UnitOccupancy).join(Unit).join(Block).where(Block.site_id == site_id)
        .options(selectinload(UnitOccupancy.person))
    )
    people: dict[int, list[dict]] = {}
    for o in occ:
        people.setdefault(o.unit_id, []).append({"occupancy_id": o.id, "person_id": o.person_id,
                                                 "name": o.person.full_name, "role": o.role, "is_primary": o.is_primary})
    out = []
    for u in site_units(db, site_id):
        b = balances[u.id]
        out.append({
            "id": u.id, "code": u.code, "block": u.block.name, "block_id": u.block_id, "number": u.number,
            "room_type": u.room_type, "area_m2": float(u.area_m2) if u.area_m2 is not None else None,
            "aidat_start_period": u.aidat_start_period, "notes": u.notes, "legacy_tags": u.legacy_tags or {},
            "people": sorted(people.get(u.id, []), key=lambda p: not p["is_primary"]),
            "balance": b.balance, "charged": b.charged, "paid": b.paid, "overdue_months": b.overdue_months,
        })
    return out


class UnitPatch(BaseModel):
    room_type: str | None = None
    area_m2: Decimal | None = None
    aidat_start_period: str | None = Field(default=None, pattern=PERIOD_RE)
    notes: str | None = None


@router.patch("/units/{unit_id}")
def update_unit(unit_id: int, body: UnitPatch, db: DB, user: Writer):
    u = db.get(Unit, unit_id)
    if not u:
        raise HTTPException(404, "Daire bulunamadı")
    get_site(db, user, u.block.site_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(u, k, v if v != "" else None)
    audit(db, user, "update", "unit", u.id, u.block.site_id, {k: str(v) for k, v in data.items()})
    db.commit()
    return {"id": u.id, "code": u.code, **{k: getattr(u, k) for k in ("room_type", "aidat_start_period", "notes")}}


class BulkUnitPatch(BaseModel):
    unit_ids: list[int]
    room_type: str | None = None
    aidat_start_period: str | None = Field(default=None, pattern=PERIOD_RE)


@router.post("/sites/{site_id}/units/bulk")
def bulk_update_units(site_id: int, body: BulkUnitPatch, db: DB, user: Writer):
    get_site(db, user, site_id)
    ids = set(body.unit_ids)
    changed = 0
    for u in site_units(db, site_id):
        if u.id in ids:
            if body.room_type is not None:
                u.room_type = body.room_type or None
            if body.aidat_start_period is not None:
                u.aidat_start_period = body.aidat_start_period
            changed += 1
    audit(db, user, "bulk_update", "unit", None, site_id, body.model_dump())
    db.commit()
    return {"changed": changed}


# --- Banka hesapları -------------------------------------------------------------------


class AccountIn(BaseModel):
    iban: str
    bank_name: str | None = None
    account_no: str | None = None
    branch: str | None = None


@router.post("/sites/{site_id}/bank-accounts", status_code=201)
def add_account(site_id: int, body: AccountIn, db: DB, user: Writer):
    get_site(db, user, site_id)
    iban = body.iban.replace(" ", "").upper()
    if not re.fullmatch(r"TR\d{24}", iban):
        raise HTTPException(400, "IBAN 'TR' + 24 rakam olmalı")
    if db.scalar(select(BankAccount).where(BankAccount.iban == iban)):
        raise HTTPException(409, "Bu IBAN zaten tanımlı")
    a = BankAccount(site_id=site_id, iban=iban, bank_name=body.bank_name, account_no=body.account_no, branch=body.branch)
    db.add(a)
    audit(db, user, "create", "bank_account", None, site_id, {"iban": iban})
    db.commit()
    return {"id": a.id, "iban": a.iban, "bank_name": a.bank_name}


# --- Gönderen hafızası -----------------------------------------------------------------


@router.get("/sites/{site_id}/aliases")
def list_aliases(site_id: int, db: DB, user: CurrentUser):
    get_site(db, user, site_id)
    units = {u.id: u.code for u in site_units(db, site_id)}
    out = []
    for a in db.scalars(select(PayerAlias).where(PayerAlias.site_id == site_id).order_by(PayerAlias.display_name)):
        out.append({"id": a.id, "display_name": a.display_name, "normalized_name": a.normalized_name, "mode": a.mode,
                    "targets": [{**t, "code": units.get(t["unit_id"])} for t in a.targets or []],
                    "source": a.source, "confirm_count": a.confirm_count, "auto_count": a.auto_count,
                    "updated_at": a.updated_at})
    return out


class AliasPatch(BaseModel):
    mode: str | None = None
    unit_ids: list[int] | None = None


@router.patch("/aliases/{alias_id}")
def update_alias(alias_id: int, body: AliasPatch, db: DB, user: Writer):
    a = db.get(PayerAlias, alias_id)
    if not a:
        raise HTTPException(404, "Kayıt bulunamadı")
    get_site(db, user, a.site_id)
    if body.unit_ids is not None:
        n = len(body.unit_ids) or 1
        a.targets = [{"unit_id": u, "ratio": round(1 / n, 4)} for u in body.unit_ids]
    if body.mode is not None:
        a.mode = body.mode
    a.source = "manual"
    a.confirm_count = max(a.confirm_count or 0, 1)
    audit(db, user, "update", "payer_alias", a.id, a.site_id, body.model_dump(exclude_none=True))
    db.commit()
    return {"id": a.id}


@router.delete("/aliases/{alias_id}", status_code=204)
def delete_alias(alias_id: int, db: DB, user: Writer):
    a = db.get(PayerAlias, alias_id)
    if not a:
        raise HTTPException(404, "Kayıt bulunamadı")
    get_site(db, user, a.site_id)
    audit(db, user, "delete", "payer_alias", a.id, a.site_id, {"name": a.display_name})
    db.delete(a)
    db.commit()
