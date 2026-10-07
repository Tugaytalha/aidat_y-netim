"""Sentetik (anonim) test dosyaları: Ziraat biçiminde ekstre ve eski takip Excel'i."""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

from openpyxl import Workbook

IBAN = "TR120001000000000000000001"


def ziraat_statement(rows: list[tuple[date, str, str, Decimal]], *, opening: Decimal = Decimal("10000.00"),
                     holder: str = "DENEME KONAKLARI SİTE YÖNETİMİ", iban: str = IBAN, skip_before: date | None = None) -> bytes:
    """rows: (tarih, fiş no, açıklama, tutar) kronolojik sırada. Dosyaya en yeni üstte yazılır (Ziraat gibi).

    skip_before: bakiyeler tüm satırlar üzerinden hesaplanır ama bu tarihten önceki satırlar dosyaya yazılmaz
    (bankadan daha kısa aralıklı ekstre indirilmiş gibi).
    """
    balance = opening
    with_bal = []
    for d, fis, desc, amt in rows:
        balance += amt
        if skip_before is None or d >= skip_before:
            with_bal.append((d, fis, desc, amt, balance))
    rows = [r[:4] for r in with_bal]
    wb = Workbook()
    ws = wb.active
    ws.title = "Hesap hareketleri"
    start = min(r[0] for r in rows)
    end = max(r[0] for r in rows)
    ws.append([f"Sayın {holder}"])
    ws.append([f"{start.day}.{start.month:02d}.{start.year} - {end.day}.{end.month:02d}.{end.year} tarihleri arasındaki hesap hareketleri listelenmektedir."])
    ws.append(["Hesap Numarası", None, "1234-5678-5001 TEST ŞUBESİ TL"])
    ws.append(["IBAN", None, iban])
    ws.append([])
    ws.append([])
    ws.append(["Hesap Hareketleri"])
    ws.append(["Tarih", "Fiş No", "Açıklama", "İşlem Tutarı", "Bakiye"])
    for d, fis, desc, amt, bal in reversed(with_bal):
        ws.append([d.strftime("%d.%m.%Y"), fis, desc, float(amt), float(bal)])
    credit = sum((r[3] for r in rows if r[3] > 0), Decimal(0))
    debit = -sum((r[3] for r in rows if r[3] < 0), Decimal(0))
    ws.append([])
    ws.append([f"Borç:{int(debit)}", f"Alacak:{int(credit):,}".replace(",", ".")])
    ws.append(["www.ziraatbank.com.tr"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


MONTHS = ["OCAK", "ŞUBAT", "MART", "NİSAN", "MAYIS", "HAZİRAN", "TEMMUZ", "AĞUSTOS", "EYLÜL", "EKİM", "KASIM", "ARALIK"]

# Blok -> [(no, isim hücresi)]
SITE_LAYOUT = {
    "A-1 BLOK": [(1, "ALİ VELİ"), (2, "AYŞE KARA / mehmet kara"), (3, "DENEME - zeynep ak"), (4, "JOHN H M SMITH")],
    "B BLOK": [(1, "HASAN YILMAZ"), (2, "FATMA DEMİR"), (3, "KEMAL ÖZ / Ali Veli"), (4, "MERVE TAN")],
    "C-2 BLOK": [(1, "AHMET KAYA"), (2, "SELİN GÜL"), (3, "MURAT CAN"), (4, "OSMAN NURİ")],
}


def tracking_excel(first_month: int = 7, first_year: int = 2025, months: int = 18) -> bytes:
    """GELİR sayfası: blok başlıkları + ay sütunları (yıl yazmaz) + ASANSÖR/Demirbaş + karalama sütunları."""
    wb = Workbook()
    ws = wb.active
    ws.title = "GELİR"
    ws.append([None, None, None, "not satırı"])
    header_months = [MONTHS[(first_month - 1 + i) % 12] for i in range(months)]
    for bi, (block, units) in enumerate(SITE_LAYOUT.items()):
        # sonraki bloklarda başlık ay listesi ortadan başlıyor olabilir (gerçek dosyadaki gibi)
        hdr = [None, None, block] + (header_months if bi == 0 else [None] * 3 + header_months[3:]) + ["ASANSÖR", "Demirbaş"]
        ws.append(hdr)
        for no, name in units:
            row = [("T B" if no == 4 else None), no, name]
            for m in range(months):
                y = first_year + (first_month - 1 + m) // 12
                mm = (first_month - 1 + m) % 12 + 1
                if (y, mm) >= (2026, 1):
                    amount = 3500
                else:
                    amount = 3000
                if (y, mm) > (2026, 9):
                    row.append(None)  # gelecek aylar boş
                elif no == 2 and bi == 1 and m == 5:
                    row.append("3000+1500")  # metin ifade
                elif no == 3 and m % 4 == 0:
                    row.append(None)  # ödenmemiş aylar
                else:
                    row.append(amount)
            row += [1250 if no != 4 else None, 2000 if no == 1 else None, None, 21000 if no == 4 else None]
            ws.append(row)
    ws.append([None, None, "işlenmeyen"])
    ws.append([None, None, "bir not 5000 tl"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def sample_bank_rows() -> list[tuple[date, str, str, Decimal]]:
    D = Decimal
    return [
        (date(2026, 1, 5), "F00001", "Gönd: ALİ VELİ A1 blok daire 1 ocak aidatı 0205-Kuveyt Türk Katılım Bankası A.Ş. FAST işlemi", D(3500)),
        (date(2026, 1, 6), "F00002", "Gönd: HASAN YILMAZ B1/1 0064-Türkiye İş Bankası A.Ş. FAST işlemi", D(3500)),
        (date(2026, 1, 7), "F00003", "Gönd: SELİN GÜL 2/C2 numaralı daire Ocak 2026 aidatı 0205-Kuveyt Türk Katılım B", D(3500)),
        (date(2026, 1, 8), "F00004", "Gönd: OSMAN NURİ 0205-Kuveyt Türk Katılım Bankası A.Ş. FAST işlemi", D(3500)),
        (date(2026, 1, 8), "F00005", "Gönd: JOHN H M SMITH 0205-Kuveyt Türk Katılım Bankası A.Ş. FAST işlemi", D(3500)),
        (date(2026, 1, 9), "F00006", "For January 2026, A1 4 and B2 4 JOHN SMITH Ziraat Mobil Havale", D(7000)),
        (date(2026, 1, 10), "F00007", "Gönd: BAŞKA BİRİ a1 blok daire 2 mehmet kara 0012-Türkiye Halk Bankası A.Ş. FAST işlemi", D(3500)),
        (date(2026, 1, 11), "F00008", "Gönd: TANIMSIZ KİŞİ aidat 0062-Türkiye Garanti Bankası A.Ş. FAST işlemi", D(3500)),
        (date(2026, 1, 12), "F00009", "Gülfa A.Blok.Daire.3 site aidatı ZEYNEP AK Ziraat Mobil Havale", D(3500)),
        (date(2026, 1, 15), "F00010", "Gönd: MERVE TAN B blok ,d:4 - şubat aidat 0064-Türkiye İş Bankası A.Ş. FAST işlemi", D(3500)),
        (date(2026, 2, 3), "F00011", "Gönd: AHMET KAYA 5/2c kat 2 d.1 demirbaş 0064-Türkiye İş Bankası A.Ş. FAST işlemi", D(2000)),
        (date(2026, 2, 4), "F00012", "Gönd: KEMAL ÖZ B1 Blok Daire:3 0067-Yapı ve Kredi Bankası A.Ş. FAST işlemi", D(3500)),
    ]
