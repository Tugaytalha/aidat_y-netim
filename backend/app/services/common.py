"""Dönem (YYYY-MM), Türkçe sayı ve tarih yardımcıları."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

TWO = Decimal("0.01")


def period_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def period_parts(period: str) -> tuple[int, int]:
    y, m = period.split("-")
    return int(y), int(m)


def add_months(period: str, n: int) -> str:
    y, m = period_parts(period)
    idx = y * 12 + (m - 1) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def period_range(start: str, end: str) -> list[str]:
    """start ve end dahil dönem listesi."""
    out: list[str] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(TWO)


_TR_THOUSANDS = re.compile(r"^-?\d{1,3}(\.\d{3})+$")


def parse_tr_number(value) -> Decimal | None:
    """Excel hücresinden tutar okur: 3600.0, '1.086.785', '3.500,00', '-1.250,50', '3600 TL'."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return money(value)
    s = str(value).strip().replace("TL", "").replace("tl", "").replace("₺", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif _TR_THOUSANDS.match(s):
        s = s.replace(".", "")
    try:
        return money(s)
    except InvalidOperation:
        return None


def parse_amount_expression(value) -> Decimal | None:
    """'3600+70.000' gibi hücreleri toplar. Okunamazsa None."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        return parse_tr_number(value)
    parts = [p for p in re.split(r"\+", value.strip()) if p.strip()]
    if not parts:
        return None
    total = Decimal(0)
    for p in parts:
        n = parse_tr_number(p)
        if n is None:
            return None
        total += n
    return money(total)


_DATE_RE = re.compile(r"^\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4})")


def parse_tr_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    m = _DATE_RE.match(str(value))
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None
