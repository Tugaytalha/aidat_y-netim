"""Banka açıklamasından blok/daire çıkarımı.

Desenler sitenin blok adlarından ve takma adlarından dinamik üretilir. Örnekler (Gülfa ekstresinden):
  'A2 Blok D:3', 'A-1 Blok Daire-2', 'C1 BLOK DAİRE1', 'B1/2', '7/C2', 'C2 Flat 4', 'C1 6',
  '5/c2 kat 2 d.3', 'C2 / BODRUM / 2', 'B blok ,d:2', 'A.Blok.Daire.6' (A1/A2 belirsiz)
Bulunan numara bloğun gerçek daire numaralarıyla doğrulanır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.matching.normalize import fold


@dataclass(frozen=True)
class BlockInfo:
    id: int
    name: str
    unit_numbers: frozenset[int]
    aliases: tuple[str, ...] = ()


@dataclass
class UnitHit:
    block_ids: tuple[int, ...]
    number: int | None
    # strong: "daire/blok/d:" gibi anahtar kelimeli; normal: "C1 6", "A2/2"; weak: "5/1c" gibi ters yazım; block: sadece blok
    strength: str
    span: tuple[int, int]
    text: str
    candidates: list[tuple[int, int]] = field(default_factory=list)  # (block_id, number)


_SEP = r"[\s\-/.:,_#()]*"
_FILLERS = (
    r"kat\s*[:.]?\s*\d{1,2}(?![0-9])|blok|block|blogu|bina|daire|dairesi|dair|numarali|numara|nolu|no|flat|apt|"
    r"bodrum|zemin|giris|d"
)
_FWD_RE = re.compile(rf"^(?P<fill>(?:{_SEP}(?:{_FILLERS})(?![a-z]))*){_SEP}(?P<num>\d{{1,3}})(?![0-9])(?![.,]\d)")
# Numaradan sonra tek harflik yazım hatası ("Daire-2ı") sadece anahtar kelimeli kalıpta kabul edilir
_TYPO_SUFFIX_RE = re.compile(r"^[a-z](?![a-z0-9])")
_REV_RE = re.compile(r"(?<![0-9.,])(?P<num>\d{1,3})\s*/\s*$")
_REV_STRONG_RE = re.compile(r"^\s*(numarali|nolu|no|daire)")
_BLOK_WORD_RE = re.compile(r"\b(blok|block|blogu)\b")

_MASKS = [
    re.compile(r"(?<!\d)\d{1,2}[./]\d{1,2}[./]\d{2,4}(?!\d)"),  # tarih
    re.compile(r"(?<!\d)\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?(?!\d)"),  # 3.500 / 70.000 / 1.000,00
    re.compile(r"(?<!\d)\d+\s*(?:tl|try|lira)\b"),  # 3500 tl
    re.compile(r"(?<!\d)\d{4,}(?!\d)"),  # yıl, uzun sayılar
]


def mask_numbers(text: str) -> str:
    for rx in _MASKS:
        text = rx.sub(lambda m: "#" * len(m.group(0)), text)
    return text


def _alias_forms(name: str) -> set[str]:
    n = fold(name).replace(" ", "")
    forms = {n}
    m = re.fullmatch(r"([a-z]+)[-_. ]?(\d+)", n)
    if m:
        letters, digits = m.groups()
        forms |= {
            f"{letters}{digits}", f"{letters}-{digits}", f"{letters} {digits}", f"{letters}.{digits}",
            f"{letters}_{digits}", f"{digits}{letters}", f"{digits}-{letters}",
        }
    m = re.fullmatch(r"(\d+)[-_. ]?([a-z]+)", n)
    if m:
        digits, letters = m.groups()
        forms |= {f"{digits}{letters}", f"{letters}{digits}", f"{letters}-{digits}", f"{letters} {digits}"}
    return forms


class UnitExtractor:
    def __init__(self, blocks: list[BlockInfo]):
        self.blocks = {b.id: b for b in blocks}
        alias_map: dict[str, set[int]] = {}
        for b in blocks:
            for form in _alias_forms(b.name) | {fold(a) for a in b.aliases if a.strip()}:
                alias_map.setdefault(form, set()).add(b.id)
        # Harf grubu: "A" adlı blok yoksa "a" -> A1, A2 (belirsiz)
        exact_letters = {fold(b.name) for b in blocks if re.fullmatch(r"[A-Za-z]", b.name)}
        for b in blocks:
            m = re.fullmatch(r"([a-z]+)\d+", fold(b.name).replace("-", ""))
            if m and m.group(1) not in exact_letters:
                alias_map.setdefault(m.group(1), set()).add(b.id)
        self.alias_map = {k: tuple(sorted(v)) for k, v in alias_map.items()}
        ordered = sorted(self.alias_map, key=len, reverse=True)
        alt = "|".join(re.escape(a).replace(r"\ ", r"\s*") for a in ordered)
        self._alias_re = re.compile(rf"(?<![a-z0-9])(?P<alias>{alt})(?![a-z0-9])") if ordered else None

    def extract(self, text: str) -> list[UnitHit]:
        if not self._alias_re:
            return []
        t = mask_numbers(fold(text))
        hits: list[UnitHit] = []
        for m in self._alias_re.finditer(t):
            alias_txt = re.sub(r"\s+", " ", m.group("alias"))
            block_ids = self.alias_map.get(alias_txt) or self.alias_map.get(alias_txt.replace(" ", ""))
            if not block_ids:
                continue
            single_letter = len(alias_txt) == 1
            rest = t[m.end() :]
            hit: UnitHit | None = None

            fm = _FWD_RE.match(rest)
            if fm:
                fill = fm.group("fill")
                between = rest[: fm.start("num")]
                has_kw = bool(re.search(r"[a-z]", fill))
                after = rest[fm.end() :]
                if after[:1].isalpha() and not (has_kw and _TYPO_SUFFIX_RE.match(after)):
                    fm = None
                elif single_letter and not (_BLOK_WORD_RE.search(fill) or re.fullmatch(r"\s*[/\-.]\s*", between)):
                    fm = None
                else:
                    hit = UnitHit(
                        block_ids=block_ids,
                        number=int(fm.group("num")),
                        strength="strong" if has_kw else "normal",
                        span=(m.start(), m.end() + fm.end()),
                        text=t[m.start() : m.end() + fm.end()],
                    )
            if hit is None and not single_letter:
                rm = _REV_RE.search(t[: m.start()])
                if rm:
                    strong = bool(_REV_STRONG_RE.match(rest))
                    hit = UnitHit(
                        block_ids=block_ids,
                        number=int(rm.group("num")),
                        strength="normal" if strong else "weak",
                        span=(rm.start(), m.end()),
                        text=t[rm.start() : m.end()],
                    )
            if hit is None:
                if single_letter and not _BLOK_WORD_RE.match(rest.lstrip(" .-,")):
                    continue
                hit = UnitHit(block_ids=block_ids, number=None, strength="block", span=(m.start(), m.end()), text=alias_txt)
            hits.append(hit)
        return self._validate(hits)

    def _validate(self, hits: list[UnitHit]) -> list[UnitHit]:
        out: list[UnitHit] = []
        seen: set[tuple] = set()
        for h in hits:
            if h.number is not None:
                valid = tuple(bid for bid in h.block_ids if h.number in self.blocks[bid].unit_numbers)
                if not valid:
                    h = UnitHit(block_ids=h.block_ids, number=None, strength="block", span=h.span, text=h.text)
                else:
                    h.block_ids = valid
                    h.candidates = [(bid, h.number) for bid in valid]
            key = (h.block_ids, h.number)
            if key in seen:
                continue
            seen.add(key)
            out.append(h)
        # Aynı blok için numaralı bir isabet varsa salt-blok isabetini at
        numbered_blocks = {bid for h in out if h.number is not None for bid in h.block_ids}
        return [h for h in out if h.number is not None or not set(h.block_ids) <= numbered_blocks]
