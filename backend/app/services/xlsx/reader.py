"""Stil hatalarına dayanıklı xlsx okuyucu.

Banka çıktılarının bir kısmı bozuk styles.xml içeriyor (openpyxl açamıyor). Önce python-calamine
denenir; o da başarısız olursa sayfa XML'i doğrudan okunur. Her iki yol da satırları mutlak
koordinatlarla (A1 = rows[0][0]) döndürür.
"""

from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Any

Rows = list[list[Any]]

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def read_workbook(data: bytes) -> dict[str, Rows]:
    try:
        return _read_calamine(data)
    except Exception:
        return _read_raw_xml(data)


def _read_calamine(data: bytes) -> dict[str, Rows]:
    from python_calamine import CalamineWorkbook

    wb = CalamineWorkbook.from_filelike(io.BytesIO(data))
    out: dict[str, Rows] = {}
    for name in wb.sheet_names:
        sheet = wb.get_sheet_by_name(name)
        rows = sheet.to_python(skip_empty_area=False)
        out[name] = [[None if v == "" else v for v in row] for row in rows]
    return out


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group(0)
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _read_raw_xml(data: bytes) -> dict[str, Rows]:
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))

    # sayfa adı -> dosya yolu
    wb_root = ET.fromstring(z.read("xl/workbook.xml"))
    rels_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rel_target = {r.get("Id"): r.get("Target") for r in rels_root}
    sheets: list[tuple[str, str]] = []
    for s in wb_root.iter(f"{{{_NS['m']}}}sheet"):
        rid = s.get(f"{{{_REL_NS}}}id")
        target = rel_target.get(rid, "")
        path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        sheets.append((s.get("name"), path))

    out: dict[str, Rows] = {}
    for name, path in sheets:
        root = ET.fromstring(z.read(path))
        rows: Rows = []
        for row in root.iter(f"{{{_NS['m']}}}row"):
            r_attr = row.get("r")
            row_idx = int(r_attr) - 1 if r_attr else len(rows)
            while len(rows) <= row_idx:
                rows.append([])
            cells: list[Any] = []
            for c in row.findall("m:c", _NS):
                ref = c.get("r")
                col = _col_index(ref) if ref else len(cells)
                while len(cells) <= col:
                    cells.append(None)
                cells[col] = _cell_value(c, shared)
            rows[row_idx] = cells
        width = max((len(r) for r in rows), default=0)
        out[name] = [r + [None] * (width - len(r)) for r in rows]
    return out


def _cell_value(c: ET.Element, shared: list[str]) -> Any:
    t = c.get("t")
    v = c.find("m:v", _NS)
    if t == "s" and v is not None:
        return shared[int(v.text)]
    if t == "inlineStr":
        is_ = c.find("m:is", _NS)
        return "".join(x.text or "" for x in is_.iter(f"{{{_NS['m']}}}t")) if is_ is not None else None
    if v is None or v.text is None:
        return None
    if t in ("str", "e"):
        return v.text
    if t == "b":
        return v.text == "1"
    try:
        f = float(v.text)
        return int(f) if f.is_integer() and "." not in v.text and "E" not in v.text.upper() else f
    except ValueError:
        return v.text
