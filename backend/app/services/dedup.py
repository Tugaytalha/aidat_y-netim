"""Ekstre tekrarlarının ayıklanması ve bakiye zinciri (süreklilik) kontrolü."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.bank_parsers.base import ParsedTransaction


def _fmt(d: Decimal | None) -> str:
    return "" if d is None else f"{d:.2f}"


def dedup_key(iban: str, t: ParsedTransaction) -> str:
    """Açıklama anahtara katılmaz: bankalar aynı işlemin metnini farklı uzunlukta kesebiliyor.

    Bakiye varsa (tarih, fiş, tutar, bakiye) yeterince ayırt edicidir. Bakiye yoksa aynı gün içindeki
    kronolojik sıra eklenir.
    """
    parts = [iban.replace(" ", "").upper(), t.txn_date.isoformat(), (t.receipt_no or "").strip(), _fmt(t.amount)]
    if t.balance_after is not None:
        parts.append(_fmt(t.balance_after))
    else:
        parts.append(f"seq{t.seq}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


@dataclass
class ChainRow:
    txn_date: date
    seq: int
    amount: Decimal
    balance_after: Decimal | None


def find_gaps(rows: list[ChainRow]) -> list[dict]:
    """Gün bazında bakiye zinciri: önceki günün kapanışı + günün hareketleri = günün kapanışı olmalı.

    Gün içi sıradan bağımsızdır (aynı gün birden çok işlemde sıralama belirsiz olabilir).
    """
    by_day: dict[date, list[ChainRow]] = defaultdict(list)
    for r in rows:
        if r.balance_after is not None:
            by_day[r.txn_date].append(r)
    days = sorted(by_day)
    gaps: list[dict] = []
    prev_close: Decimal | None = None
    prev_day: date | None = None
    for d in days:
        items = sorted(by_day[d], key=lambda r: r.seq)
        day_sum = sum((r.amount for r in items), Decimal(0))
        balances = {r.balance_after for r in items}
        if prev_close is not None:
            expected = prev_close + day_sum
            if expected not in balances:
                gaps.append(
                    {
                        "after": prev_day.isoformat(),
                        "before": d.isoformat(),
                        "expected_balance": str(expected),
                        "message": f"{prev_day:%d.%m.%Y} ile {d:%d.%m.%Y} arasında eksik hareket olabilir "
                        f"(beklenen bakiye {expected:.2f})",
                    }
                )
                # Zinciri bu günün kapanışından yeniden başlat
                prev_close = items[-1].balance_after
                prev_day = d
                continue
            prev_close = expected
        else:
            first = items[0]
            prev_close = first.balance_after - first.amount + day_sum
        prev_day = d
    return gaps
