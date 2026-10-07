"""Eşleştirme motoru: sinyalleri birleştirip daire adaylarını puanlar.

Veritabanından bağımsızdır; SiteContext bellekte sitenin yapısını taşır. Böylece testler DB'siz çalışır.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal

from rapidfuzz import fuzz

from app.services.common import money, period_of
from app.services.matching.categorize import categorize
from app.services.matching.extract_period import extract_periods
from app.services.matching.extract_unit import BlockInfo, UnitExtractor
from app.services.matching.normalize import fold, normalize_name, parse_description

# Sinyal ağırlıkları
W_ALIAS_CONFIRMED = 0.97
W_ALIAS_AUTO = 0.90
W_AMBIGUOUS = 0.50
W_CODE = {"strong": 0.92, "normal": 0.85, "weak": 0.55}
W_PERSON_IDENTICAL = 0.90  # benzerlik >= 97: tek başına otomatik eşleşme eşiğine ulaşır
W_PERSON_EXACT = 0.88
W_PERSON_CLOSE = 0.75
W_PERSON_IN_BODY = 0.80
W_AMOUNT_EXACT = 0.30
W_AMOUNT_MULTIPLE = 0.10
W_BLOCK_HINT = 0.30
MAX_SECOND_FOR_AUTO = 0.60


@dataclass
class UnitRef:
    id: int
    block_id: int
    number: int
    code: str
    room_type: str | None = None


@dataclass
class PersonRef:
    id: int
    name: str
    key: str
    unit_ids: tuple[int, ...]


@dataclass
class AliasRef:
    key: str
    mode: str
    targets: list[dict]
    source: str
    confirm_count: int = 0


@dataclass
class SiteContext:
    site_id: int
    site_name: str
    blocks: list[BlockInfo]
    units: dict[int, UnitRef]
    persons: list[PersonRef]
    aliases: dict[str, AliasRef]
    tariff: Callable[[int, str], Decimal | None] = lambda unit_id, period: None
    one_off_amounts: dict[Decimal, str] = field(default_factory=dict)
    threshold: float = 0.90

    def __post_init__(self) -> None:
        self.extractor = UnitExtractor(self.blocks)
        self.unit_index = {(u.block_id, u.number): u.id for u in self.units.values()}


@dataclass
class Signal:
    kind: str  # alias | code | person | body_name | amount | block
    weight: float
    detail: str


@dataclass
class Candidate:
    unit_id: int
    code: str
    score: float
    signals: list[Signal]


@dataclass
class MatchResult:
    payer_name: str | None
    payer_key: str
    sender_bank: str | None
    channel: str | None
    category: str
    category_explicit: bool
    stated_periods: list[str]
    period_note: str | None
    candidates: list[Candidate]
    split: list[dict] | None
    decision: str  # auto | suggest | none
    conflict: bool
    method: str | None
    reasons: list[str]
    highlights: list[dict]

    def to_json(self) -> dict:
        d = asdict(self)
        d["split"] = [{"unit_id": s["unit_id"], "amount": str(s["amount"])} for s in (self.split or [])] or None
        return d


def name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    score = fuzz.token_sort_ratio(a, b)
    ta, tb = a.split(), b.split()
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    long_small = [t for t in small if len(t) > 2]
    if len(long_small) >= 2 and all(any(fuzz.ratio(t, u) >= 90 for u in big) for t in long_small):
        score = max(score, 95.0)
    return float(score)


def _noisy_or(weights: list[float]) -> float:
    p = 1.0
    for w in weights:
        p *= 1 - w
    return round(1 - p, 4)


def split_amount(amount: Decimal, unit_ids: list[int], ctx: SiteContext, period: str, ratios: list[float] | None = None) -> list[dict]:
    n = len(unit_ids)
    if ratios and len(ratios) == n and sum(ratios) > 0:
        total = sum(ratios)
        parts = [money((amount * Decimal(str(r / total))).quantize(Decimal("0.01"), rounding=ROUND_DOWN)) for r in ratios]
    else:
        tariffs = [ctx.tariff(u, period) for u in unit_ids]
        if all(tariffs) and sum(tariffs) > 0 and amount % sum(tariffs) == 0:
            k = amount / sum(tariffs)
            parts = [money(t * k) for t in tariffs]
        else:
            share = (amount / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            parts = [share] * n
    parts[0] += amount - sum(parts)  # kuruş farkı ilk daireye
    return [{"unit_id": u, "amount": p} for u, p in zip(unit_ids, parts)]


def match_transaction(ctx: SiteContext, description: str, amount: Decimal, txn_date: date) -> MatchResult:
    pd = parse_description(description, ctx.site_name)
    payer_key = normalize_name(pd.payer_name)
    period = period_of(txn_date)
    category, cat_explicit = categorize(pd.body, amount, ctx.one_off_amounts)
    stated, period_note = extract_periods(pd.body, txn_date)
    reasons: list[str] = []
    highlights: list[dict] = []

    signals: dict[int, list[Signal]] = {}

    def add(unit_id: int, sig: Signal) -> None:
        signals.setdefault(unit_id, []).append(sig)

    if amount <= 0:
        return MatchResult(
            pd.payer_name, payer_key, pd.sender_bank, pd.channel, "diger", False, stated, period_note, [], None,
            "none", False, None, ["Çıkış işlemi (gider modülü kapsamı dışında)"], highlights,
        )

    # 1) Öğrenilmiş gönderen hafızası
    alias = ctx.aliases.get(payer_key) if payer_key else None
    alias_split: list[int] | None = None
    if alias and alias.targets:
        confirmed = alias.source in ("manual", "excel") or alias.confirm_count > 0
        w = W_ALIAS_CONFIRMED if confirmed else W_ALIAS_AUTO
        target_ids = [t["unit_id"] for t in alias.targets if t["unit_id"] in ctx.units]
        if alias.mode == "ambiguous":
            for uid in target_ids:
                add(uid, Signal("alias", W_AMBIGUOUS, f"Gönderen birden çok daire için ödeme yapmış: {pd.payer_name}"))
        else:
            for uid in target_ids:
                add(uid, Signal("alias", w, f"Gönderen hafızası: {pd.payer_name}"))
            if alias.mode == "split" and len(target_ids) > 1:
                alias_split = target_ids

    # 2) Açıklamadaki blok/daire kodu
    hits = ctx.extractor.extract(pd.body)
    code_units: list[int] = []
    block_hints: set[int] = set()
    for h in hits:
        highlights.append({"text": h.text, "strength": h.strength})
        if h.number is None:
            block_hints |= set(h.block_ids)
            continue
        cand_units = [ctx.unit_index[c] for c in h.candidates if c in ctx.unit_index]
        if len(cand_units) == 1:
            add(cand_units[0], Signal("code", W_CODE[h.strength], f"Açıklamada daire kodu: '{h.text}'"))
            if h.strength != "weak":
                code_units.append(cand_units[0])
        else:
            for uid in cand_units:
                add(uid, Signal("code", W_AMBIGUOUS, f"Belirsiz blok: '{h.text}'"))

    # 3) Kişi adı benzerliği (gönderen adı + açıklamada geçen sakin adları)
    body_tokens = set(normalize_name(pd.body).split())
    sims = {p.id: (name_similarity(payer_key, p.key) if payer_key else 0.0) for p in ctx.persons}
    # Tam eşleşen bir kişi varsa yakın benzerler (aynı soyadlı aile üyeleri gibi) sinyal üretmez
    close_floor = 92 if sims and max(sims.values()) >= 92 else 85
    for p in ctx.persons:
        if not p.unit_ids:
            continue
        sim = sims[p.id]
        if sim >= 97:
            w = W_PERSON_IDENTICAL
        elif sim >= 92:
            w = W_PERSON_EXACT
        elif sim >= close_floor:
            w = W_PERSON_CLOSE
        else:
            w = 0.0
            ptoks = [t for t in p.key.split() if len(t) > 1]
            if len(ptoks) >= 2 and all(t in body_tokens for t in ptoks) and p.key != payer_key:
                for uid in p.unit_ids:
                    add(uid, Signal("body_name", W_PERSON_IN_BODY if len(p.unit_ids) == 1 else W_AMBIGUOUS,
                                    f"Açıklamada sakin adı: {p.name}"))
        if w:
            for uid in p.unit_ids:
                add(uid, Signal("person", w if len(p.unit_ids) == 1 else W_AMBIGUOUS,
                                f"Gönderen adı '{pd.payer_name}' ≈ '{p.name}' (%{sim:.0f})"))

    # 4) Tutar ve blok ipucu: sadece belirsiz olmayan bir sinyali olan dairelere destek
    for uid in [u for u, sigs in signals.items() if any(s.weight > W_AMBIGUOUS for s in sigs)]:
        t = ctx.tariff(uid, period)
        if t and t > 0:
            if amount == t:
                add(uid, Signal("amount", W_AMOUNT_EXACT, f"Tutar dairenin aidatına eşit ({t})"))
            elif amount % t == 0 and amount / t <= 12:
                add(uid, Signal("amount", W_AMOUNT_MULTIPLE, f"Tutar aidatın {int(amount / t)} katı"))
        if block_hints and ctx.units[uid].block_id in block_hints:
            add(uid, Signal("block", W_BLOCK_HINT, "Açıklamada blok adı geçiyor"))

    candidates = sorted(
        (
            Candidate(uid, ctx.units[uid].code, _noisy_or([s.weight for s in sigs]), sigs)
            for uid, sigs in signals.items()
        ),
        key=lambda c: -c.score,
    )

    # Bölüştürme önerisi
    split: list[dict] | None = None
    distinct_codes = list(dict.fromkeys(code_units))
    if alias_split:
        ratios = [float(t.get("ratio") or 1) for t in alias.targets if t["unit_id"] in alias_split]
        split = split_amount(amount, alias_split, ctx, period, ratios)
        reasons.append("Gönderen hafızasındaki bölüştürme kuralı uygulandı")
    elif len(distinct_codes) > 1:
        split = split_amount(amount, distinct_codes, ctx, period)
        reasons.append("Açıklamada birden çok daire geçiyor: bölüştürme önerildi")

    # Çelişki: açık daire kodu ile güçlü kişi/alias sinyali farklı daireyi gösteriyor
    conflict = False
    strong_identity = {
        uid for uid, sigs in signals.items()
        if any(s.kind in ("alias", "person") and s.weight >= W_PERSON_EXACT for s in sigs)
    }
    if distinct_codes and strong_identity and not (strong_identity & set(distinct_codes)):
        conflict = True
        codes = ", ".join(ctx.units[u].code for u in distinct_codes)
        ids = ", ".join(ctx.units[u].code for u in strong_identity)
        reasons.append(f"Çelişki: açıklamadaki daire ({codes}) ile gönderen kimliği ({ids}) farklı")

    decision = "none"
    method = None
    if split:
        same_as_alias = alias_split is not None and (not distinct_codes or set(distinct_codes) <= set(alias_split))
        decision = "auto" if same_as_alias and not conflict else "suggest"
        method = "alias" if alias_split else "code"
    elif candidates:
        top = candidates[0]
        second = candidates[1].score if len(candidates) > 1 else 0.0
        top_kinds = {s.kind for s in top.signals if s.weight > W_AMBIGUOUS}
        if top.score >= ctx.threshold and not conflict and second < MAX_SECOND_FOR_AUTO and top_kinds - {"amount", "block"}:
            decision = "auto"
        elif top.score >= 0.5:
            decision = "suggest"
            if second >= MAX_SECOND_FOR_AUTO and top.score >= ctx.threshold:
                reasons.append("Birden fazla güçlü aday var")
        best = max(top.signals, key=lambda s: s.weight)
        method = {"body_name": "person", "amount": "code", "block": "code"}.get(best.kind, best.kind)

    if decision == "none" and not candidates:
        reasons.append("Açıklamada daire bilgisi yok ve gönderen tanınmıyor")

    return MatchResult(
        payer_name=pd.payer_name,
        payer_key=payer_key,
        sender_bank=pd.sender_bank,
        channel=pd.channel,
        category=category,
        category_explicit=cat_explicit,
        stated_periods=stated,
        period_note=period_note,
        candidates=candidates[:5],
        split=split,
        decision=decision,
        conflict=conflict,
        method=method,
        reasons=reasons,
        highlights=highlights,
    )


__all__ = [
    "AliasRef", "Candidate", "MatchResult", "PersonRef", "SiteContext", "UnitRef",
    "fold", "match_transaction", "name_similarity", "split_amount",
]
