"""Türkçe güvenli metin katlama ve banka açıklaması temizleme."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_TR_MAP = str.maketrans(
    {
        "İ": "i", "I": "i", "ı": "i", "Ş": "s", "ş": "s", "Ğ": "g", "ğ": "g",
        "Ü": "u", "ü": "u", "Ö": "o", "ö": "o", "Ç": "c", "ç": "c",
        "Â": "a", "â": "a", "Î": "i", "î": "i", "Û": "u", "û": "u",
    }
)


def fold(s: str | None) -> str:
    """Türkçe harfleri ASCII'ye indirger, küçük harfe çevirir, boşlukları sadeleştirir.

    Python'un lower() fonksiyonu 'İ' için 'i̇' üretir; bu yüzden önce çeviri tablosu uygulanır.
    """
    if not s:
        return ""
    s = s.translate(_TR_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s.lower()).strip()


def normalize_name(s: str | None) -> str:
    """İsim karşılaştırma anahtarı: harf dışı karakterler atılır, tek harfli ardışık baş harfler birleştirilir.

    'LEYLA H M  TESTOGLU' -> 'leyla hm testoglu'; 'SAMI M M D ORNEKZADE' -> 'sami mmd ornekzade'
    """
    f = fold(s)
    f = re.sub(r"[^a-z ]+", " ", f)
    tokens = f.split()
    out: list[str] = []
    buf = ""
    for t in tokens:
        if len(t) == 1:
            buf += t
            continue
        if buf:
            out.append(buf)
            buf = ""
        out.append(t)
    if buf:
        out.append(buf)
    return " ".join(out)


# --- Banka açıklaması ayrıştırma -------------------------------------------------

# "0205-Kuveyt Türk Katılım Bankası A.Ş. FAST işlemi" (kesik de olabilir: "0205-Kuveyt Türk Katılım B")
_SENDER_BANK_RE = re.compile(r"\s(\d{4})-([A-Za-zÇĞİÖŞÜçğıöşü][^\n]*)$")
_CHANNEL_RE = re.compile(
    r"\s(Ziraat Mobil Havale|Ziraat Mobil Hav\w*|Ziraat Mobil|Ziraat|İnternet Havale|Internet Havale|"
    r"İnternet Hav\w*|ATM Havale|Şube Havale)\s*$",
    re.IGNORECASE,
)
_GOND_RE = re.compile(r"^\s*G[öo]nd\s*:\s*", re.IGNORECASE)

# Gönderen adının parçası olamayacak (katlanmış) kelimeler
STOPWORDS = {
    "aidat", "aidati", "aidatlari", "aidet", "aydat", "ayi", "aylik", "bedeli", "olarak", "odemesi", "odeme",
    "odemesidir", "site", "sitesi", "blok", "blogu", "daire", "dairesi", "icin", "ve", "tl", "demirbas",
    "asansor", "ucreti", "ucret", "kirasi", "kira", "no", "nolu", "monthly", "payment", "for", "and",
    "ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim", "kasim",
    "aralik", "fark", "farki", "eski", "borc", "borclari", "son", "iki", "gonderilen", "gonderen",
    "konaklari", "konaklar", "evleri", "rezidans", "residence", "apartmani", "toplu", "konut",
}

# Site adındaki genel kelimeler; site adından "durdurucu ifade" üretirken atlanır
_GENERIC_SITE_WORDS = {"site", "sitesi", "yonetimi", "konaklari", "konaklar", "evleri", "rezidans", "apartmani"}


def site_stop_phrase(site_name: str | None) -> tuple[str, ...]:
    """'GÜLFA MAMİK KONAKLARI' -> ('gulfa',). İsim toplanırken bu kelimeyle başlayan dizide durulur.

    Sadece ilk anlamlı kelime kullanılır; böylece site adını soyadı olarak taşıyan kişiler
    (ör. "AYŞE MAMİK") bozulmaz.
    """
    for tok in fold(site_name).split():
        if tok not in _GENERIC_SITE_WORDS and len(tok) > 2:
            return (tok,)
    return ()


@dataclass
class ParsedDescription:
    raw: str
    body: str  # banka/kanal gürültüsü atılmış serbest metin
    payer_name: str | None
    sender_bank: str | None
    channel: str | None


def _is_upper_token(tok: str) -> bool:
    letters = [c for c in tok if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters) and not any(c.isdigit() for c in tok)


def _clean_token(tok: str) -> str:
    return tok.strip(",.;:()[]{}\"'")


def _collect_name(
    tokens: list[str], *, from_end: bool, max_tokens: int = 6, extra_stop: frozenset[str] = frozenset()
) -> list[str]:
    seq = list(reversed(tokens)) if from_end else tokens
    picked: list[str] = []
    seen: set[str] = set()
    for raw_tok in seq:
        tok = _clean_token(raw_tok)
        if not tok:
            if picked:
                break
            continue
        if tok in ("/", "-", "&"):
            if not from_end and picked:
                picked.append(tok)
                continue
            break
        if not _is_upper_token(tok):
            break
        key = fold(tok)
        if key in STOPWORDS or key in extra_stop:
            break
        if len(key) > 1 and key in seen:  # "MUSTAFA KOÇ MUSTAFA KOÇ" tekrarını kes
            break
        if len(key) > 1:
            seen.add(key)
        picked.append(tok)
        if len(picked) >= max_tokens and from_end:
            break
    if from_end:
        picked.reverse()
    # baştaki/sondaki ayraçlar ve sondaki tek harfler ("MURAT UÇAR C" -> "MURAT UÇAR")
    while picked and (picked[-1] in ("/", "-", "&") or len(fold(picked[-1])) == 1):
        picked.pop()
    while picked and picked[0] in ("/", "-", "&"):
        picked.pop(0)
    return picked


def parse_description(raw: str, site_name: str | None = None) -> ParsedDescription:
    extra_stop = frozenset(site_stop_phrase(site_name))
    text = (raw or "").strip()
    sender_bank = None
    channel = None

    m = _SENDER_BANK_RE.search(text)
    if m:
        sender_bank = f"{m.group(1)}-{m.group(2).replace(' FAST işlemi', '').strip()}"
        text = text[: m.start()].strip()
        channel = "FAST" if "FAST" in m.group(2) or raw.strip().startswith(("Gönd", "Gond")) else "EFT"

    m = _CHANNEL_RE.search(text)
    if m:
        channel = m.group(1)
        text = text[: m.start()].strip()

    payer_tokens: list[str] = []
    gond = _GOND_RE.match(text)
    if gond:
        text = text[gond.end() :]
        tokens = text.split()
        payer_tokens = _collect_name(tokens, from_end=False, extra_stop=extra_stop)
        if not payer_tokens:
            # Karışık harfli isim ("Zeynep Ak Gülfa sitesi") -> ilk iki büyük harfle başlayan kelime
            caps = []
            for t in tokens:
                if t[:1].isupper() and t[1:].islower() and t.isalpha():
                    caps.append(t)
                    if len(caps) == 2:
                        break
                else:
                    break
            payer_tokens = caps
    elif channel:
        payer_tokens = _collect_name(text.split(), from_end=True, max_tokens=5, extra_stop=extra_stop)
    else:
        payer_tokens = _collect_name(text.split(), from_end=False, extra_stop=extra_stop)

    payer = " ".join(payer_tokens) or None
    return ParsedDescription(raw=raw, body=text, payer_name=payer, sender_bank=sender_bank, channel=channel)
