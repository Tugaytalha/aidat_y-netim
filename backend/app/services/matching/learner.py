"""Öğrenen gönderen hafızası (payer_alias)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PayerAlias
from app.services.matching.normalize import normalize_name


def _targets(unit_amounts: list[tuple[int, Decimal]]) -> list[dict]:
    total = sum((a for _, a in unit_amounts), Decimal(0)) or Decimal(1)
    return [{"unit_id": uid, "ratio": float(round(a / total, 4))} for uid, a in unit_amounts]


def learn(db: Session, site_id: int, payer_name: str | None, unit_amounts: list[tuple[int, Decimal]], *, source: str) -> PayerAlias | None:
    """source='manual': kullanıcı onayı (hafıza bu kararla güncellenir).
    source='auto': açık daire koduyla otomatik eşleşme; mevcut farklı bir kayıt varsa 'belirsiz' yapılır.
    """
    key = normalize_name(payer_name)
    if not key or not unit_amounts:
        return None
    alias = db.scalar(select(PayerAlias).where(PayerAlias.site_id == site_id, PayerAlias.normalized_name == key))
    unit_ids = [u for u, _ in unit_amounts]
    if source == "manual":
        if alias is None:
            alias = PayerAlias(site_id=site_id, normalized_name=key, display_name=payer_name or key)
            db.add(alias)
        alias.mode = "split" if len(set(unit_ids)) > 1 else "single"
        alias.targets = _targets(unit_amounts)
        alias.source = "manual"
        alias.confirm_count = (alias.confirm_count or 0) + 1
    else:
        if alias is None:
            alias = PayerAlias(site_id=site_id, normalized_name=key, display_name=payer_name or key,
                               mode="split" if len(set(unit_ids)) > 1 else "single",
                               targets=_targets(unit_amounts), source="auto", auto_count=1, confirm_count=0)
            db.add(alias)
        else:
            known = {t["unit_id"] for t in alias.targets}
            if set(unit_ids) <= known:
                alias.auto_count = (alias.auto_count or 0) + 1
            elif alias.source != "manual":
                alias.mode = "ambiguous"
                alias.targets = [{"unit_id": u, "ratio": None} for u in sorted(known | set(unit_ids))]
    db.flush()
    return alias
