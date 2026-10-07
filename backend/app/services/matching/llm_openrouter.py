"""Opsiyonel LLM önerisi (OpenRouter, OpenAI uyumlu chat completions).

Sadece kural motorunun çözemediği işlemler için, kullanıcı "AI ile öner" dediğinde çalışır. Sonuç asla
otomatik onaylanmaz; inceleme kuyruğunda öneri olarak gösterilir. KVKK: açıklama ve sakin isimleri üçüncü
tarafa gider, bu yüzden site ayarında ayrıca açılmalıdır. Bakiye/borç bilgisi gönderilmez.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal

import httpx

from app.core.config import get_settings
from app.services.matching.scorer import SiteContext


class LLMUnavailable(Exception):
    pass


SYSTEM_PROMPT = """Bir site yönetim şirketinde banka havalelerini dairelerle eşleştiren bir asistansın.
Sana bir banka işlemi açıklaması, tutarı, tarihi ve sitedeki dairelerin listesi (kod ve sakin adları) verilecek.
Görevin: ödemenin hangi daire(ler) için yapıldığını bulmak.

Kurallar:
- Sadece listede bulunan daire kodlarını kullan. Emin değilsen boş liste döndür; tahmin uydurma.
- Açıklamada birden çok daire geçiyorsa tutarı dairelere böl ("split"). Bölüştürme toplamı işlem tutarına eşit olmalı.
- Gönderen kişi daire sakininden farklı olabilir (aile üyesi, şirket, kiracı).
- Blok yazımları çeşitlidir: "7/C2" = C2 blok 7 nolu daire, "5/1C" adres numarasıdır ve C1 bloğu anlamına gelebilir.
- Kategori: aidat, demirbas, asansor, ek_butce veya diger.
- Açıklamada geçen ayları YYYY-MM biçiminde stated_periods olarak ver.

Yalnızca şu JSON nesnesini döndür, başka metin yazma:
{"units": ["C2-7"], "split": [{"unit": "C2-7", "amount": 3600}], "category": "aidat",
 "stated_periods": ["2026-09"], "confidence": 0.0-1.0, "reason": "kısa Türkçe gerekçe"}"""


def _unit_listing(ctx: SiteContext) -> str:
    names: dict[int, list[str]] = {}
    for p in ctx.persons:
        for uid in p.unit_ids:
            names.setdefault(uid, []).append(p.name)
    lines = []
    for uid, u in sorted(ctx.units.items(), key=lambda kv: kv[1].code):
        lines.append(f"{u.code}: {', '.join(names.get(uid, [])) or '-'}")
    return "\n".join(lines)


def _parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise LLMUnavailable("Model JSON döndürmedi")
    return json.loads(m.group(0))


def suggest(ctx: SiteContext, description: str, amount: Decimal, txn_date: str) -> dict:
    s = get_settings()
    if not s.openrouter_api_key:
        raise LLMUnavailable("OPENROUTER_API_KEY tanımlı değil")
    user = (
        f"Site: {ctx.site_name}\nDaireler (kod: sakinler):\n{_unit_listing(ctx)}\n\n"
        f"İşlem tarihi: {txn_date}\nTutar: {amount} TL\nAçıklama: {description}"
    )
    try:
        resp = httpx.post(
            f"{s.openrouter_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {s.openrouter_api_key}", "X-Title": "Ortabahce Aidat"},
            json={
                "model": s.openrouter_model,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
                "response_format": {"type": "json_object"},
                "max_tokens": 1024,
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        raise LLMUnavailable(f"OpenRouter hatası: {e.response.status_code} {e.response.text[:200]}") from e
    except (httpx.HTTPError, KeyError, IndexError) as e:
        raise LLMUnavailable(f"OpenRouter'a ulaşılamadı: {e}") from e

    data = _parse_json(content)
    code_to_id = {u.code.upper(): uid for uid, u in ctx.units.items()}
    units = [code_to_id[c.upper()] for c in data.get("units", []) if isinstance(c, str) and c.upper() in code_to_id]
    split = []
    for part in data.get("split") or []:
        code = str(part.get("unit", "")).upper()
        if code in code_to_id:
            try:
                split.append({"unit_id": code_to_id[code], "amount": str(Decimal(str(part.get("amount"))))})
            except Exception:  # noqa: BLE001 - modelden gelen bozuk sayı
                continue
    if split and sum(Decimal(p["amount"]) for p in split) != amount:
        split = []  # tutar tutmuyorsa bölüştürmeyi gösterme
    return {
        "unit_ids": units,
        "split": split or None,
        "category": data.get("category") if data.get("category") in ("aidat", "demirbas", "asansor", "ek_butce", "diger") else None,
        "stated_periods": [p for p in data.get("stated_periods", []) if isinstance(p, str) and re.fullmatch(r"\d{4}-\d{2}", p)],
        "confidence": float(data.get("confidence") or 0),
        "reason": str(data.get("reason") or "")[:500],
        "model": s.openrouter_model,
    }
