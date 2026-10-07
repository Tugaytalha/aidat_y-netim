from __future__ import annotations

import hashlib
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, Writer, audit, get_site
from app.models import BankTransaction, PaymentAllocation, Site, Unit
from app.services.common import money
from app.services.matching import service as matching
from app.services.matching.llm_openrouter import LLMUnavailable
from app.services.matching.llm_openrouter import suggest as llm_suggest

router = APIRouter(prefix="/api", tags=["transactions"])


def txn_out(t: BankTransaction, codes: dict[int, str]) -> dict:
    info = t.match_info or {}
    return {
        "id": t.id, "source": t.source, "txn_date": t.txn_date, "receipt_no": t.receipt_no, "description": t.description,
        "amount": t.amount, "balance_after": t.balance_after, "status": t.status, "payer_name": t.payer_name,
        "sender_bank": t.sender_bank, "channel": t.channel, "category_hint": t.category_hint,
        "stated_periods": t.stated_periods or [], "note": t.note,
        "allocations": [{"id": a.id, "unit_id": a.unit_id, "code": codes.get(a.unit_id), "amount": a.amount,
                         "category": a.category, "period": a.period, "method": a.method, "confidence": a.confidence,
                         "confirmed_at": a.confirmed_at} for a in t.allocations],
        "candidates": [{"unit_id": c["unit_id"], "code": c["code"], "score": c["score"],
                        "signals": [{"kind": s["kind"], "weight": s["weight"], "detail": s["detail"]} for s in c["signals"]]}
                       for c in info.get("candidates", [])],
        "split": info.get("split"), "decision": info.get("decision"), "conflict": info.get("conflict", False),
        "reasons": info.get("reasons", []), "highlights": info.get("highlights", []), "period_note": info.get("period_note"),
        "llm": info.get("llm"),
    }


def _codes(db, site_id: int) -> dict[int, str]:
    from app.services.ledger import site_units

    return {u.id: u.code for u in site_units(db, site_id)}


@router.get("/sites/{site_id}/transactions")
def list_transactions(
    site_id: int, db: DB, user: CurrentUser, status: str | None = None, q: str | None = None, unit_id: int | None = None,
    source: str | None = "bank", date_from: date | None = None, date_to: date | None = None, page: int = 1,
    page_size: int = 50,
):
    get_site(db, user, site_id)
    stmt = select(BankTransaction).where(BankTransaction.site_id == site_id)
    if source:
        stmt = stmt.where(BankTransaction.source == source)
    if status:
        stmt = stmt.where(BankTransaction.status.in_(status.split(",")))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(BankTransaction.description.ilike(like), BankTransaction.payer_name.ilike(like)))
    if unit_id:
        stmt = stmt.where(BankTransaction.id.in_(select(PaymentAllocation.transaction_id).where(PaymentAllocation.unit_id == unit_id)))
    if date_from:
        stmt = stmt.where(BankTransaction.txn_date >= date_from)
    if date_to:
        stmt = stmt.where(BankTransaction.txn_date <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    page_size = max(1, min(page_size, 500))
    rows = db.scalars(
        stmt.options(selectinload(BankTransaction.allocations))
        .order_by(BankTransaction.txn_date.desc(), BankTransaction.seq.desc(), BankTransaction.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    codes = _codes(db, site_id)
    return {"total": total, "page": page, "page_size": page_size, "items": [txn_out(t, codes) for t in rows]}


def _txn(db, user, txn_id: int) -> BankTransaction:
    t = db.get(BankTransaction, txn_id)
    if not t:
        raise HTTPException(404, "İşlem bulunamadı")
    get_site(db, user, t.site_id)
    return t


@router.get("/transactions/{txn_id}")
def get_transaction(txn_id: int, db: DB, user: CurrentUser):
    t = _txn(db, user, txn_id)
    return txn_out(t, _codes(db, t.site_id))


class AllocationIn(BaseModel):
    unit_id: int
    amount: Decimal = Field(gt=0)
    category: str = "aidat"


class ConfirmIn(BaseModel):
    allocations: list[AllocationIn]
    remember: bool = True
    note: str | None = None


@router.post("/transactions/{txn_id}/confirm")
def confirm_transaction(txn_id: int, body: ConfirmIn, db: DB, user: Writer):
    t = _txn(db, user, txn_id)
    codes = _codes(db, t.site_id)
    for a in body.allocations:
        if a.unit_id not in codes:
            raise HTTPException(400, "Daire bu siteye ait değil")
    try:
        matching.confirm(db, t, [a.model_dump() for a in body.allocations], user_id=user.id, remember=body.remember,
                         note=body.note)
    except matching.MatchError as e:
        db.rollback()
        raise HTTPException(400, str(e)) from e
    audit(db, user, "confirm", "transaction", t.id, t.site_id,
          {"allocations": [{"unit": codes[a.unit_id], "amount": str(a.amount)} for a in body.allocations],
           "remember": body.remember})
    db.commit()
    db.refresh(t)
    return txn_out(t, codes)


class IgnoreIn(BaseModel):
    note: str | None = None


@router.post("/transactions/{txn_id}/ignore")
def ignore_transaction(txn_id: int, body: IgnoreIn, db: DB, user: Writer):
    t = _txn(db, user, txn_id)
    matching.ignore(db, t, note=body.note)
    audit(db, user, "ignore", "transaction", t.id, t.site_id, {"note": body.note})
    db.commit()
    return txn_out(t, _codes(db, t.site_id))


@router.post("/transactions/{txn_id}/reset")
def reset_transaction(txn_id: int, db: DB, user: Writer):
    t = _txn(db, user, txn_id)
    if t.source != "bank":
        raise HTTPException(400, "Sadece banka işlemleri yeniden eşleştirilebilir")
    matching.reset(db, t)
    audit(db, user, "reset", "transaction", t.id, t.site_id)
    db.commit()
    db.refresh(t)
    return txn_out(t, _codes(db, t.site_id))


@router.post("/transactions/{txn_id}/llm-suggest")
def llm_suggest_transaction(txn_id: int, db: DB, user: Writer):
    t = _txn(db, user, txn_id)
    site = db.get(Site, t.site_id)
    if not site.llm_enabled:
        raise HTTPException(400, "Bu site için AI önerisi kapalı (Site ayarları → AI önerisi)")
    ctx = matching.build_context(db, t.site_id)
    try:
        result = llm_suggest(ctx, t.description, Decimal(t.amount), t.txn_date.isoformat())
    except LLMUnavailable as e:
        raise HTTPException(503, str(e)) from e
    info = dict(t.match_info or {})
    info["llm"] = result
    t.match_info = info
    audit(db, user, "llm_suggest", "transaction", t.id, t.site_id, {"model": result.get("model")})
    db.commit()
    return txn_out(t, _codes(db, t.site_id))


class BulkConfirmIn(BaseModel):
    transaction_ids: list[int]
    remember: bool = True


@router.post("/sites/{site_id}/transactions/bulk-confirm")
def bulk_confirm(site_id: int, body: BulkConfirmIn, db: DB, user: Writer):
    """Seçili önerilerin en iyi adayını (ya da bölüştürme önerisini) onaylar."""
    get_site(db, user, site_id)
    done, skipped = 0, []
    for tid in body.transaction_ids:
        t = db.get(BankTransaction, tid)
        if not t or t.site_id != site_id or t.status != "suggested":
            skipped.append(tid)
            continue
        info = t.match_info or {}
        if info.get("split"):
            allocs = [{"unit_id": s["unit_id"], "amount": s["amount"], "category": t.category_hint or "aidat"} for s in info["split"]]
        elif info.get("candidates"):
            allocs = [{"unit_id": info["candidates"][0]["unit_id"], "amount": t.amount, "category": t.category_hint or "aidat"}]
        else:
            skipped.append(tid)
            continue
        matching.confirm(db, t, allocs, user_id=user.id, remember=body.remember)
        done += 1
    audit(db, user, "bulk_confirm", "transaction", None, site_id, {"count": done})
    db.commit()
    return {"confirmed": done, "skipped": skipped}


@router.post("/sites/{site_id}/transactions/rematch")
def rematch(site_id: int, db: DB, user: Writer):
    """Bekleyen (öneri/eşleşmemiş) işlemleri güncel hafıza ve tarifelerle yeniden değerlendirir."""
    get_site(db, user, site_id)
    pending = list(db.scalars(select(BankTransaction).where(
        BankTransaction.site_id == site_id, BankTransaction.source == "bank",
        BankTransaction.status.in_(("suggested", "unmatched")))))
    stats = matching.run_matching(db, site_id, pending)
    db.commit()
    return {"processed": len(pending), **stats}


class ManualPaymentIn(BaseModel):
    txn_date: date
    amount: Decimal = Field(gt=0)
    unit_id: int
    category: str = "aidat"
    description: str = Field(min_length=2)


@router.post("/sites/{site_id}/transactions/manual", status_code=201)
def manual_payment(site_id: int, body: ManualPaymentIn, db: DB, user: Writer):
    """Elden/nakit ödeme girişi (bankada görünmeyen)."""
    get_site(db, user, site_id)
    unit = db.get(Unit, body.unit_id)
    if not unit or unit.block.site_id != site_id:
        raise HTTPException(400, "Daire bulunamadı")
    # Elden ödemeler bankada olmadığından tekrar kontrolü yapılmaz; benzersiz anahtar üretilir
    key = hashlib.sha256(f"manual|{uuid.uuid4().hex}".encode()).hexdigest()
    t = BankTransaction(site_id=site_id, source="manual", txn_date=body.txn_date, description=body.description,
                        amount=money(body.amount), direction="in", dedup_key=key, status="unmatched",
                        category_hint=body.category)
    db.add(t)
    db.flush()
    matching.confirm(db, t, [{"unit_id": body.unit_id, "amount": body.amount, "category": body.category}],
                     user_id=user.id, remember=False)
    audit(db, user, "create", "manual_payment", t.id, site_id, {"unit": unit.code, "amount": str(body.amount)})
    db.commit()
    db.refresh(t)
    return txn_out(t, _codes(db, site_id))
