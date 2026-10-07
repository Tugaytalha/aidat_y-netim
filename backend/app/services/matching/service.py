"""Eşleştirme motorunun veritabanı tarafı: bağlam kurma, sonuçları uygulama, onay/yok sayma."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models import (
    BankTransaction, Block, ChargeBatch, PayerAlias, PaymentAllocation, Person, Site, UnitOccupancy,
)
from app.services.common import money, period_of
from app.services.ledger import site_units, tariff_resolver_for_site
from app.services.matching import learner
from app.services.matching.extract_unit import BlockInfo
from app.services.matching.scorer import (
    W_AMBIGUOUS, AliasRef, MatchResult, PersonRef, SiteContext, UnitRef, match_transaction,
)


class MatchError(Exception):
    pass


def build_context(db: Session, site_id: int) -> SiteContext:
    site = db.get(Site, site_id)
    blocks = list(db.scalars(select(Block).where(Block.site_id == site_id).options(selectinload(Block.units))))
    units = site_units(db, site_id)
    block_infos = [
        BlockInfo(b.id, b.name, frozenset(u.number for u in b.units), tuple(b.aliases or ())) for b in blocks
    ]
    unit_refs = {u.id: UnitRef(u.id, u.block_id, u.number, u.code, u.room_type) for u in units}

    occ = db.execute(
        select(Person, UnitOccupancy.unit_id).join(UnitOccupancy, UnitOccupancy.person_id == Person.id)
        .where(Person.site_id == site_id)
    )
    persons: dict[int, PersonRef] = {}
    for p, unit_id in occ:
        ref = persons.setdefault(p.id, PersonRef(p.id, p.full_name, p.normalized_name, ()))
        ref.unit_ids = tuple(sorted(set(ref.unit_ids) | {unit_id}))

    aliases = {
        a.normalized_name: AliasRef(a.normalized_name, a.mode, a.targets or [], a.source, a.confirm_count or 0)
        for a in db.scalars(select(PayerAlias).where(PayerAlias.site_id == site_id))
    }
    one_off = {
        Decimal(b.amount): b.type for b in db.scalars(select(ChargeBatch).where(ChargeBatch.site_id == site_id))
    }
    threshold = site.auto_match_threshold or get_settings().auto_match_threshold
    return SiteContext(
        site_id=site_id, site_name=site.name, blocks=block_infos, units=unit_refs, persons=list(persons.values()),
        aliases=aliases, tariff=tariff_resolver_for_site(db, site_id), one_off_amounts=one_off, threshold=threshold,
    )


def _primary_person(db: Session, unit_id: int) -> int | None:
    occ = db.scalar(
        select(UnitOccupancy).where(UnitOccupancy.unit_id == unit_id)
        .order_by(UnitOccupancy.is_primary.desc(), UnitOccupancy.id.desc())
    )
    return occ.person_id if occ else None


def apply_result(db: Session, ctx: SiteContext, txn: BankTransaction, result: MatchResult) -> None:
    txn.payer_name = result.payer_name
    txn.sender_bank = result.sender_bank
    txn.channel = result.channel
    txn.category_hint = result.category
    txn.stated_periods = result.stated_periods
    info = result.to_json()
    txn.match_info = info

    if txn.amount <= 0:
        txn.status = "ignored"
        txn.note = txn.note or "Çıkış işlemi"
        return
    if result.decision == "auto":
        if result.split:
            parts = [(s["unit_id"], s["amount"]) for s in result.split]
            confidence = min(c.score for c in result.candidates if c.unit_id in {p[0] for p in parts}) if result.candidates else None
        else:
            parts = [(result.candidates[0].unit_id, txn.amount)]
            confidence = result.candidates[0].score
        _write_allocations(db, txn, parts, result.category, method=result.method or "code", confidence=confidence)
        txn.status = "matched"
        top = result.candidates[0] if result.candidates else None
        ambiguous_person = any(
            s.kind == "person" and s.weight <= W_AMBIGUOUS for c in result.candidates for s in c.signals
        )
        if result.method == "code" and top and not ambiguous_person and not result.split:
            learner.learn(db, ctx.site_id, result.payer_name, parts, source="auto")
    elif result.decision == "suggest":
        txn.status = "suggested"
    else:
        txn.status = "unmatched"


def _write_allocations(
    db: Session, txn: BankTransaction, parts: list[tuple[int, Decimal]], category: str, *, method: str,
    confidence: float | None, user_id: int | None = None, categories: list[str] | None = None,
) -> None:
    for a in list(txn.allocations):
        db.delete(a)
    db.flush()
    period = period_of(txn.txn_date)
    now = datetime.now() if user_id else None
    for i, (unit_id, amount) in enumerate(parts):
        db.add(PaymentAllocation(
            transaction_id=txn.id, site_id=txn.site_id, unit_id=unit_id, person_id=_primary_person(db, unit_id),
            amount=money(amount), category=(categories[i] if categories else category), period=period,
            method=method, confidence=confidence, confirmed_by=user_id, confirmed_at=now,
        ))
    db.flush()


def run_matching(db: Session, site_id: int, txns: list[BankTransaction], ctx: SiteContext | None = None) -> dict:
    ctx = ctx or build_context(db, site_id)
    stats = {"auto": 0, "suggest": 0, "none": 0, "ignored": 0}
    for t in txns:
        if t.status in ("matched", "ignored") and t.allocations:
            continue
        result = match_transaction(ctx, t.description, Decimal(t.amount), t.txn_date)
        apply_result(db, ctx, t, result)
        if t.status == "ignored":
            stats["ignored"] += 1
        else:
            stats[result.decision] += 1
        # Yeni öğrenilen alias'lar aynı içe aktarım içindeki sonraki işlemlere de yansısın
        if t.status == "matched" and result.method == "code":
            ctx.aliases = {
                a.normalized_name: AliasRef(a.normalized_name, a.mode, a.targets or [], a.source, a.confirm_count or 0)
                for a in db.scalars(select(PayerAlias).where(PayerAlias.site_id == site_id))
            }
    return stats


def confirm(
    db: Session, txn: BankTransaction, allocations: list[dict], *, user_id: int, remember: bool = True, note: str | None = None
) -> BankTransaction:
    """allocations: [{"unit_id", "amount", "category"}]. Toplam işlem tutarını aşamaz."""
    if not allocations:
        raise MatchError("En az bir daire seçilmeli")
    total = sum((money(a["amount"]) for a in allocations), Decimal(0))
    if total > money(txn.amount):
        raise MatchError(f"Dağıtılan toplam ({total}) işlem tutarını ({txn.amount}) aşıyor")
    if total <= 0:
        raise MatchError("Dağıtılan tutar sıfırdan büyük olmalı")
    parts = [(int(a["unit_id"]), money(a["amount"])) for a in allocations]
    cats = [a.get("category") or txn.category_hint or "aidat" for a in allocations]
    _write_allocations(db, txn, parts, cats[0], method="manual", confidence=1.0, user_id=user_id, categories=cats)
    txn.status = "matched"
    if note is not None:
        txn.note = note
    if remember and txn.payer_name:
        learner.learn(db, txn.site_id, txn.payer_name, parts, source="manual")
    return txn


def ignore(db: Session, txn: BankTransaction, *, note: str | None) -> BankTransaction:
    for a in list(txn.allocations):
        db.delete(a)
    txn.status = "ignored"
    txn.note = note or "Aidat dışı"
    db.flush()
    return txn


def reset(db: Session, txn: BankTransaction) -> BankTransaction:
    """Eşleşmeyi kaldırır ve motoru yeniden çalıştırır (otomatik karar yine uygulanabilir)."""
    for a in list(txn.allocations):
        db.delete(a)
    db.flush()
    db.refresh(txn)
    txn.status = "unmatched"
    ctx = build_context(db, txn.site_id)
    result = match_transaction(ctx, txn.description, Decimal(txn.amount), txn.txn_date)
    apply_result(db, ctx, txn, result)
    return txn
