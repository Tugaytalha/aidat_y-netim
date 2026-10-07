"""Ödeme kategorisi tahmini: aidat / demirbaş / asansör / ek bütçe."""

from __future__ import annotations

import re
from decimal import Decimal

from app.services.matching.normalize import fold

_RULES: list[tuple[str, re.Pattern]] = [
    ("asansor", re.compile(r"asansor|elevator|elevetor|lift")),
    ("ek_butce", re.compile(r"ek\s*butce")),
    ("demirbas", re.compile(r"demirba|demirbs|sifrematik|sifre|klavye|password|kapi\s*sifre|hidrolik|aydinlatma")),
    ("aidat", re.compile(r"aidat|aidet|aydat|aidati|monthly|bakim\s*ucret|uyelik|kira|awaa?ed|fark")),
]


def categorize(text: str, amount: Decimal | None = None, one_off_amounts: dict[Decimal, str] | None = None) -> tuple[str, bool]:
    """(kategori, açık_ifade_mi). Anahtar kelime yoksa tutar bir tek seferlik tahakkuka eşitse o kategori."""
    t = fold(text)
    hits = [cat for cat, rx in _RULES if rx.search(t)]
    if hits:
        # "Asansör tadilat ek demirbaş" -> asansör (ilk kural); aidat da geçiyorsa karışık ödemedir -> aidat
        if "aidat" in hits and len(hits) > 1:
            return "aidat", True
        return hits[0], True
    if amount is not None and one_off_amounts:
        cat = one_off_amounts.get(amount)
        if cat:
            return cat, False
    return "aidat", False
