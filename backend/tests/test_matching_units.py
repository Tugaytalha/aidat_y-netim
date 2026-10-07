"""Metin işleme: normalize, gönderen adı, daire kodu, dönem ve kategori çıkarımı.

Açıklama kalıpları gerçek Gülfa ekstresindeki yazımlardan alınmış, isimler anonimleştirilmiştir.
"""

from datetime import date

import pytest

from app.services.matching.categorize import categorize
from app.services.matching.extract_period import extract_periods
from app.services.matching.extract_unit import BlockInfo, UnitExtractor, mask_numbers
from app.services.matching.normalize import fold, normalize_name, parse_description

BLOCKS = [
    BlockInfo(1, "A1", frozenset(range(1, 7))),
    BlockInfo(2, "A2", frozenset(range(1, 7))),
    BlockInfo(3, "B", frozenset(range(1, 7)), ("b1", "b2")),
    BlockInfo(4, "C1", frozenset(range(1, 9)), ("5/1c",)),
    BlockInfo(5, "C2", frozenset(range(1, 9)), ("5/2c",)),
]
NAMES = {1: "A1", 2: "A2", 3: "B", 4: "C1", 5: "C2"}
EX = UnitExtractor(BLOCKS)


def codes(text: str) -> list[str]:
    out = []
    for h in EX.extract(text):
        blocks = "/".join(NAMES[b] for b in h.block_ids)
        out.append(f"{blocks}-{h.number}" if h.number is not None else f"{blocks}-?")
    return out


def test_fold_turkish_i():
    assert fold("DAİRE İÇİN ŞUBAT") == "daire icin subat"
    assert fold("ISPARTA ıslak") == "isparta islak"
    assert normalize_name("LEYLA H M  TESTOGLU") == "leyla hm testoglu"
    assert normalize_name("SAMI M M D ORNEKZADE") == "sami mmd ornekzade"


@pytest.mark.parametrize(
    "raw,payer,channel",
    [
        ("Gönd: ALİ VELİ A2 blok daire 6 Ali veli 0203-Albaraka Türk Katılım Bankası A.Ş. FAST işlemi", "ALİ VELİ", "FAST"),
        ("Gönd: AYŞE KARA / ÖR-NEK AKADEMİ EĞİTİM DANIŞMANLIK VE YAZILIM B1 Daire 1 0067-Yapı", "AYŞE KARA / ÖR-NEK AKADEMİ EĞİTİM DANIŞMANLIK", "FAST"),
        ("Gönd: MUSTAFA KOÇ MUSTAFA KOÇ ARALIK KİRASI 0062-Türkiye Garanti Bankası A.Ş. FAST işlemi", "MUSTAFA KOÇ", "FAST"),
        ("Gönd: SAMI N S S TESTER 0205-Kuveyt Türk Katılım Bankası A.Ş. FAST işlemi", "SAMI N S S TESTER", "FAST"),
        ("Gönd: Zeynep Ak Gülfa sitesi A1 Daire 3 Zeynep Ak Temmuz 0157-Enpara Bank A.Ş. FAST işlemi", "Zeynep Ak", "FAST"),
        ("Gönd: KEMAL ÖZ C 1 Blok Daire 0046-Akbank T.A.Ş. FAST işlemi", "KEMAL ÖZ", "FAST"),
        ("Monthly Payment C1 6 JOHN PARK JOHN PARK Ziraat Mobil Havale", "JOHN PARK", "Ziraat Mobil Havale"),
        ("B blok ,daire 2 - mayıs aidat Ali Veli ALİ VELİ Ziraat Mobil Havale", "ALİ VELİ", "Ziraat Mobil Havale"),
        ("HASAN YILMAZ GÜLFA SİTESİ C1 BLOK DAİRE 7 EKİM 2026 AYI AİDAT BEDELİ OLARAK HASAN YILMAZ İnternet Havale",
         "HASAN YILMAZ", "İnternet Havale"),
        ("For March 2026 including Elevetor Fee for John Park JOHN PARK Ziraat", "JOHN PARK", "Ziraat"),
    ],
)
def test_parse_description_payer(raw, payer, channel):
    pd = parse_description(raw, site_name="LALE YILDIZ KONAKLARI")
    assert pd.payer_name == payer
    assert pd.channel == channel


def test_site_name_does_not_stick_to_payer_but_surname_survives():
    site = "LALE YILDIZ KONAKLARI"
    pd = parse_description("Gönd: HAKAN TEST LALE YILDIZ KONAKLARI C1-1 OCAK 2026 AİDATI 0062-Türkiye Garanti", site)
    assert pd.payer_name == "HAKAN TEST"
    # Site adındaki kelimeyi soyadı olarak taşıyan kişi bozulmamalı
    pd = parse_description("Gönd: AYŞE YILDIZ 0205-Kuveyt Türk Katılım Bankası A.Ş. FAST işlemi", site)
    assert pd.payer_name == "AYŞE YILDIZ"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A2 blok daire 6", ["A2-6"]),
        ("B1 Daire 1 (ali veli) Mart-Nisan", ["B-1"]),
        ("A2 Blok D:3 Eylül 2026", ["A2-3"]),
        ("C1 BLOK DAİRE 7 EKİM 2026 AYI", ["C1-7"]),
        ("gülfa mamikler aidat ödemesi B1- Daire:5", ["B-5"]),
        ("A-1 Blok Daire-2 Eylül ayı Aidat ödemesi 3.500 tl", ["A1-2"]),
        ("C1 BLOK DAİRE1 EYLÜL AYI SİTE AİDATI", ["C1-1"]),
        ("ali veli - B1/2", ["B-2"]),
        ("Gülfa Mamik Konakları 5/1C Blok Daire:4 Merkez Mah.", ["C1-4"]),
        ("A.Blok.Daire.6 site aidatı", ["A1/A2-6"]),
        ("Monthly Payment C1 6", ["C1-6"]),
        ("C 1 Blok Daire", ["C1-?"]),
        ("ida c1-2 aidat faki", ["C1-2"]),
        ("ida c1_2 aidat", ["C1-2"]),
        ("5/c2 kat 2 d.3 eylul aidati", ["C2-3"]),
        ("5/2c kat: 2 d.3 basiskle", ["C2-3"]),
        ("A2/2 Eylül 2026 Aidatı", ["A2-2"]),
        ("7/C2 numaralı dairenin Eylül 2026 ayı", ["C2-7"]),
        ("C2 Flat 4", ["C2-4"]),
        ("C2 flat 4/aidat Mart", ["C2-4"]),
        ("For password management system, C1/6 and B2/5", ["C1-6", "B-5"]),
        ("For June 2026, B2 5 (Ali Veli), C1 6 (John Park)", ["B-5", "C1-6"]),
        ("c2/8", ["C2-8"]),
        ("C2 / BODRUM / 2", ["C2-2"]),
        ("a2 blok daire 1 yunus test", ["A2-1"]),
        ("C2 BLOK DAİRE 3 NO EV SAHİBİNİN", ["C2-3"]),
        ("C2 DAİRE3", ["C2-3"]),
        ("C1 BLOK 7 NOLU DAİRE DEMİRBAŞ", ["C1-7"]),
        ("B blok ,d:2 - ali veli-ekBütçe", ["B-2"]),
        ("B blok ,daire 2 - mayıs aidat", ["B-2"]),
        ("ali veli,B/2,demirbaş", ["B-2"]),
        ("A 2 blok daire 4  Haziran aidatı", ["A2-4"]),
        ("Blok c2 daire 1 kalan aidat bedeli", ["C2-1"]),
        ("Raif Test demirbsş Ödemesi A-1 Blok Daire-2ı", ["A1-2"]),
        ("sk 5/1C/2c blok başiskele aidat", ["C1-?", "C2-?"]),
        ("07.08.2026 talebi-şifrematik/aydınlatma gideri C2 Blok D:7", ["C2-7"]),
        ("C2/7 Asansör Tadilat Ek Demirbaş Ücreti - 10.04.2026", ["C2-7"]),
        ("GÜLFA MAMİK KONAKLARI C1-1 OCAK 2026 AİDATI", ["C1-1"]),
        ("Talebiniz üzerine, Ocak 2025 kararı demirbaş - 1.000 TL", []),
        ("For March and April 2026 including Elevetor Fee for John, Ali Al Test", []),
        ("SAAD F F M A TEST Aidat", []),
        ("C1 BLOK DAİRE 9", ["C1-?"]),  # C1'de 9 numaralı daire yok -> numara reddedilir
    ],
)
def test_extract_unit(text, expected):
    assert codes(text) == expected


def test_mask_numbers():
    assert "3.500" not in mask_numbers("aidat 3.500 tl ve 10.04.2026 tarihli 2026")
    assert mask_numbers("daire 5") == "daire 5"


@pytest.mark.parametrize(
    "text,txn,expected",
    [
        ("Eylül 2026 aidatı", date(2026, 10, 1), ["2026-09"]),
        ("Mart-Nisan", date(2026, 10, 4), ["2026-03", "2026-04"]),
        ("C1 daire 8 aralık ayı aidat", date(2026, 2, 5), ["2025-12"]),
        ("C1 daire 8 hazitan ayı aidat", date(2026, 1, 26), ["2025-06"]),
        ("agustos2026", date(2026, 8, 31), ["2026-08"]),
        ("For March and April 2026 including", date(2026, 4, 13), ["2026-03", "2026-04"]),
        ("EKİM 2026 AYI AİDAT BEDELİ", date(2026, 10, 1), ["2026-10"]),
        ("Eylül kirası", date(2026, 8, 3), ["2026-09"]),  # peşin ödeme: en fazla 1 ay ileri
        ("Ekim kirası", date(2026, 8, 3), ["2025-10"]),
        ("site aidatı", date(2026, 5, 1), []),
    ],
)
def test_extract_periods(text, txn, expected):
    periods, _ = extract_periods(text, txn)
    assert periods == expected


def test_period_note():
    _, note = extract_periods("C1 BLOK DAİRE 3 SON İKİ AİDAT", date(2026, 6, 1))
    assert note and "2 aylık" in note
    _, note = extract_periods("A2 Blok Daire 5 eski aidat borçları", date(2026, 5, 22))
    assert note and "eski borç" in note


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A2 Blok D:3 Demirbaş ücreti", "demirbas"),
        ("kapı şifrematik", "demirbas"),
        ("For password management system", "demirbas"),
        ("C1 BLOK DAİRE1 ASANSÖR TADİLAT ÜCRETİ", "asansor"),
        ("Bekir-ekBütçe", "ek_butce"),
        ("ARALIK KİRASI", "aidat"),
        ("aidat farki subat ve mart icin", "aidat"),
        ("Monthly Payment for May", "aidat"),
        ("resume shaqah", "aidat"),
    ],
)
def test_categorize(text, expected):
    assert categorize(text)[0] == expected
