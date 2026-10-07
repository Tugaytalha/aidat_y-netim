"""Açıklamada geçen ay bilgisini çıkarır (sadece bilgi amaçlı; ödeme gönderildiği aya yazılır)."""

from __future__ import annotations

import re
from datetime import date

from app.services.matching.normalize import fold

_TR_MONTHS = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6, "hazitan": 6, "temmuz": 7,
    "agustos": 8, "agusto": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
}
_EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
    "nov": 11, "dec": 12,
}

# Türkçe aylar ön ek olarak eşleşir ("nisanaidat", "agustos2026"); İngilizceler tam kelime olmalı
_TR_RE = re.compile(r"(?<![a-z])(" + "|".join(sorted(_TR_MONTHS, key=len, reverse=True)) + r")[a-z]*\s*[,.(]?\s*((?:19|20)\d{2})?")
_EN_RE = re.compile(
    r"(?<![a-z])(" + "|".join(sorted(_EN_MONTHS, key=len, reverse=True)) + r")(?![a-z])\s*[,.]?\s*((?:19|20)\d{2})?"
)
_RANGE_SEP_RE = re.compile(r"^\s*(?:-|ve|and|&|,|/)\s*$")
_COUNT_RE = re.compile(r"(?<![a-z])(son\s+)?(iki|uc|dort|bes|alti|2|3|4|5|6)\s+(aylik|ay|aidat)", re.I)
_COUNT_WORDS = {"iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6}


def _resolve_year(month: int, txn: date) -> int:
    """Yıl yazılmamışsa: en fazla 1 ay sonrası (peşin ödeme) kabul, değilse geçmiş yıl."""
    year = txn.year
    if (year * 12 + month) > (txn.year * 12 + txn.month + 1):
        year -= 1
    return year


def extract_periods(text: str, txn_date: date) -> tuple[list[str], str | None]:
    """(['2026-03', '2026-04'], not) döndürür. Not: 'son iki aidat' gibi sayı ifadeleri."""
    t = fold(text)
    found: list[tuple[int, int, int | None]] = []  # (pos, month, year)
    for rx, table in ((_TR_RE, _TR_MONTHS), (_EN_RE, _EN_MONTHS)):
        for m in rx.finditer(t):
            month = table[m.group(1)]
            year = int(m.group(2)) if m.group(2) else None
            found.append((m.start(), month, year))
    found.sort()
    # "Mart-Nisan 2026" -> ikisine de 2026; yılı olmayanlar sonraki yıllıdan miras alır
    periods: list[str] = []
    for i, (_pos, month, year) in enumerate(found):
        if year is None:
            for _p2, _m2, y2 in found[i + 1 :]:
                if y2 is not None:
                    year = y2
                    break
        if year is None or year > txn_date.year + 1 or year < txn_date.year - 5:
            year = _resolve_year(month, txn_date)
        p = f"{year:04d}-{month:02d}"
        if p not in periods:
            periods.append(p)

    note = None
    cm = _COUNT_RE.search(t)
    if cm:
        n = cm.group(2)
        count = _COUNT_WORDS.get(n, None) or (int(n) if n.isdigit() else None)
        if count and count > 1:
            note = f"{count} aylık ödeme ifadesi"
    if re.search(r"eski\s+(aidat\s+)?borc|kalan\s+aidat|gecmis", t):
        note = (note + "; " if note else "") + "eski borç ödemesi"
    return periods, note
