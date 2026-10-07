"""Eski takip Excel'i (ör. '14- GÜLFA MAMİK-2.xlsx' GELİR sayfası) ayrıştırıcı.

Yapı: blok başlık satırları ("A-1 BLOK" + ay adları), altında B=daire no, C=isim(ler), ay sütunlarında
o ay gönderilen ödemeler. Ay sütunlarında yıl yazmaz; ay sırası geri döndükçe yıl artırılır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.services.common import add_months, parse_amount_expression
from app.services.matching.normalize import fold, site_stop_phrase
from app.services.xlsx.reader import Rows, read_workbook

_MONTHS = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6, "temmuz": 7, "agustos": 8,
    "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
}
_ONE_OFF = {"asansor": "asansor", "demirbas": "demirbas", "ek butce": "ek_butce"}


def col_letter(idx: int) -> str:
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


@dataclass
class TrackingUnit:
    block: str
    number: int
    raw_name: str
    names: list[str]
    row: int
    payments: dict[str, Decimal] = field(default_factory=dict)  # dönem -> tutar
    raw_cells: dict[str, str] = field(default_factory=dict)  # dönem -> ham metin (ifade içerenler)
    one_offs: dict[str, Decimal] = field(default_factory=dict)  # kategori -> tutar
    tags: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrackingParse:
    sheet: str
    start_year: int
    column_periods: dict[int, str]
    one_off_columns: dict[int, str]
    units: list[TrackingUnit]
    block_order: list[str]
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def first_period(self) -> str:
        return min(self.column_periods.values())

    @property
    def last_period(self) -> str:
        return max(self.column_periods.values())


def _text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def normalize_block_name(header: str) -> str:
    """'A-1 BLOK' -> 'A1', 'C-1  BLOK' -> 'C1', 'B BLOK' -> 'B'."""
    t = fold(header)
    t = re.sub(r"\bblok(u)?\b", "", t)
    t = re.sub(r"[\s\-_.]", "", t)
    return t.upper()


def _month_of(cell: Any) -> int | None:
    f = fold(_text(cell))
    return _MONTHS.get(f)


def _one_off_of(cell: Any) -> str | None:
    f = fold(_text(cell))
    for k, v in _ONE_OFF.items():
        if f.startswith(k):
            return v
    return None


def _is_block_header(row: list[Any]) -> bool:
    c = fold(_text(row[2] if len(row) > 2 else None))
    if "blok" not in c:
        return False
    months = sum(1 for v in row[3:] if _month_of(v))
    return months >= 3


def split_names(raw: str, site_name: str | None = None) -> list[str]:
    stop = set(site_stop_phrase(site_name))
    parts = [p.strip() for p in re.split(r"\s*/\s*|\s*-\s+|\s+-\s*|(?<=[a-zçğıöşü])-(?=[A-ZÇĞİÖŞÜa-zçğıöşü])|(?<=[A-ZÇĞİÖŞÜ])-(?=[A-ZÇĞİÖŞÜa-zçğıöşü])", raw) if p.strip()]
    out = []
    for p in parts:
        toks = fold(p).split()
        if len(toks) == 1 and toks[0] in stop:  # "GÜLFA - deniz ak" -> "GÜLFA" yer tutucu
            continue
        out.append(re.sub(r"\s+", " ", p))
    return out


def _infer_start_year(seq: list[tuple[int, int]], rows: Rows, data_rows: list[int], reference: date) -> int:
    """seq: (sütun, ay). Yeterince dolu son ay sütunu referans tarihten sonra olmayacak şekilde en büyük başlangıç yılı."""
    year_off = 0
    prev = None
    rel: dict[int, tuple[int, int]] = {}
    for col, month in seq:
        if prev is not None and month < prev:
            year_off += 1
        rel[col] = (year_off, month)
        prev = month
    filled = []
    for col in rel:
        n = sum(1 for r in data_rows if col < len(rows[r]) and parse_amount_expression(rows[r][col]) not in (None, Decimal(0)))
        if n >= 5:
            filled.append(col)
    last_col = max(filled) if filled else seq[-1][0]
    off, month = rel[last_col]
    ref_idx = reference.year * 12 + reference.month - 1
    # (start + off)*12 + month-1 <= ref_idx
    start = (ref_idx - (month - 1)) // 12 - off
    return start


def parse_tracking_rows(
    rows: Rows, sheet: str, *, site_name: str | None = None, start_year: int | None = None, reference: date | None = None
) -> TrackingParse:
    reference = reference or date.today()
    header_rows = [i for i, r in enumerate(rows) if _is_block_header(r)]
    if not header_rows:
        raise ValueError(f"'{sheet}' sayfasında 'X BLOK' + ay adlarından oluşan başlık satırı bulunamadı")

    master = rows[header_rows[0]]
    seq: list[tuple[int, int]] = []
    one_off_cols: dict[int, str] = {}
    for j in range(3, len(master)):
        m = _month_of(master[j])
        if m:
            seq.append((j, m))
            continue
        o = _one_off_of(master[j])
        if o:
            one_off_cols[j] = o
    last_known_col = max([c for c, _ in seq] + list(one_off_cols))

    # Daire satırları
    data_rows: list[int] = []
    block_of_row: dict[int, str] = {}
    block_order: list[str] = []
    notes: list[str] = []
    bounds = header_rows + [len(rows)]
    for hi, h in enumerate(header_rows):
        bname = normalize_block_name(_text(rows[h][2]))
        block_order.append(bname)
        for r in range(h + 1, bounds[hi + 1]):
            row = rows[r]
            b = row[1] if len(row) > 1 else None
            c = _text(row[2] if len(row) > 2 else None)
            if isinstance(b, (int, float)) and not isinstance(b, bool) and c:
                data_rows.append(r)
                block_of_row[r] = bname
            elif c:
                notes.append(f"Satır {r + 1}: {c}")

    warnings: list[str] = []
    if start_year is None:
        start_year = _infer_start_year(seq, rows, data_rows, reference)
    col_period: dict[int, str] = {}
    year = start_year
    prev = None
    for col, month in seq:
        if prev is not None and month < prev:
            year += 1
        col_period[col] = f"{year:04d}-{month:02d}"
        prev = month

    # Diğer başlık satırları aynı sütun düzenini kullanıyor mu?
    for h in header_rows[1:]:
        for col, month in seq:
            m = _month_of(rows[h][col]) if col < len(rows[h]) else None
            if m is not None and m != month:
                warnings.append(f"Satır {h + 1}: {col_letter(col)} sütunundaki ay başlığı ilk bloktakinden farklı")
                break

    units: list[TrackingUnit] = []
    for r in data_rows:
        row = rows[r]
        raw_name = _text(row[2])
        u = TrackingUnit(
            block=block_of_row[r], number=int(row[1]), raw_name=raw_name, names=split_names(raw_name, site_name), row=r + 1
        )
        a = _text(row[0])
        if a:
            u.tags["A"] = a
        for col, period in col_period.items():
            v = row[col] if col < len(row) else None
            if v is None or v == "":
                continue
            amt = parse_amount_expression(v)
            if amt is None:
                warnings.append(f"{u.block}-{u.number} {period} ({col_letter(col)}{r + 1}): okunamayan değer '{v}'")
                continue
            if amt == 0:
                continue
            u.payments[period] = amt
            if isinstance(v, str):
                u.raw_cells[period] = v
        for col, cat in one_off_cols.items():
            v = row[col] if col < len(row) else None
            amt = parse_amount_expression(v)
            if amt:
                u.one_offs[cat] = amt
        for col in range(last_known_col + 1, len(row)):
            v = row[col]
            if v not in (None, ""):
                u.tags[col_letter(col)] = v if isinstance(v, (int, float, str)) else str(v)
        units.append(u)

    return TrackingParse(
        sheet=sheet,
        start_year=start_year,
        column_periods=dict(col_period),
        one_off_columns=one_off_cols,
        units=units,
        block_order=block_order,
        warnings=warnings,
        notes=notes,
    )


def parse_tracking_excel(
    data: bytes, *, sheet: str | None = None, site_name: str | None = None, start_year: int | None = None,
    reference: date | None = None,
) -> TrackingParse:
    wb = read_workbook(data)
    if sheet:
        if sheet not in wb:
            raise ValueError(f"'{sheet}' sayfası bulunamadı. Sayfalar: {', '.join(wb)}")
        candidates = [sheet]
    else:
        # Önce 'GELİR' adlı sayfa, sonra başlık deseni olan ilk sayfa
        candidates = sorted(wb, key=lambda n: 0 if fold(n) in ("gelir", "aidat", "tahsilat") else 1)
    last_err: Exception | None = None
    for name in candidates:
        try:
            return parse_tracking_rows(wb[name], name, site_name=site_name, start_year=start_year, reference=reference)
        except ValueError as e:
            last_err = e
    raise ValueError(str(last_err) if last_err else "Uygun sayfa bulunamadı")


__all__ = ["TrackingParse", "TrackingUnit", "add_months", "normalize_block_name", "parse_tracking_excel", "split_names"]
