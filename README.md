# Ortabahçe Aidat Yönetimi

Site yönetim şirketi için aidat takip sistemi. Banka ekstresi Excel'lerini okur, tekrarları ayıklar ve her ödemeyi
**kişi + blok/daire** ile eşleştirir. Açıklamada daire yazmayan ödemeleri de gönderen adından ve öğrenilmiş
hafızadan bulur.

## Özellikler

- **Ekstre yükleme ve dedup:** Ziraat formatı tanınır; diğer bankalar için Tarih/Açıklama/Tutar sütunları aranır.
  - Aynı dosya ya da tarih aralığı çakışan ekstreler güvenle yüklenebilir.
  - Tekrar anahtarı: IBAN + tarih + fiş no + tutar + bakiye. Ek olarak fiş no + tarih + tutar aynıysa satır yine tekrar sayılır.
  - Bakiye zinciri kontrol edilir; eksik ekstre varsa uyarı verilir.
  - Ekstre özetindeki toplamla karşılaştırma yapılır.
  - Site, IBAN'dan otomatik bulunur.
- **Eşleştirme motoru (kural tabanlı, açıklanabilir):**
  - Daire kodu çıkarımı. Tanınan yazımlar: `A2 Blok D:3`, `7/C2`, `B1/2`, `C2 Flat 4`, `5/c2 kat 2 d.3`, `C2 / BODRUM / 2`, `A.Blok.Daire.6` …
    - Blok takma adları site ayarlarından eklenir (ör. tek B bloğu için `b1`, `b2`; adres no `5/1c` → C1).
  - Gönderen adı ↔ sakin adı benzerliği (Türkçe harf ve baş harf toleranslı).
  - Tutar ↔ tarife uyumu ve tek seferlik tahakkuk tutarları (demirbaş/asansör) ipucu olarak kullanılır.
  - **Öğrenen hafıza:** İncelemede onaylanan gönderen sonraki ekstrede otomatik eşleşir. Bölüştürme kuralları da öğrenilir (ör. tek havale → C1-6 + B-5).
  - Çelişkiler (açıklamadaki daire ≠ gönderenin dairesi) her zaman incelemeye düşer.
  - Opsiyonel **OpenRouter** AI önerisi: site bazında açılır, yalnızca öneri üretir, otomatik onaylamaz.
- **Ödeme ayı:** Ödeme **gönderildiği aya** yazılır. Açıklamadaki ay ("Eylül aidatı") bilgi olarak saklanır.
- **Defter:**
  - Bakiye = Σ tahakkuk − Σ ödeme.
  - Tarifeler tüm site, oda tipi ya da daire bazında tanımlanır ve geçerlilik tarihi taşır. Toplu yüzde artışı yapılabilir.
  - Aylık tahakkuk idempotenttir.
  - Tek seferlik toplu tahakkuk (demirbaş, asansör, ek bütçe) desteklenir.
  - Elden ödeme girişi yapılabilir.
- **Takip Excel'inden içe aktarma:**
  - Bloklar, daireler, sakinler (eski/yeni) ve geçmiş ödemeler alınır.
  - Ay sütunlarında yıl yazmasa da yıl çıkarılır.
  - `3600+70.000` gibi hücreler toplanır.
  - Kesim ayı ile çift sayım önlenir; kesim sonrası Excel değerleri mutabakat raporunda kullanılır.
- **Açılış bakiyesi sihirbazı:** Tarife geçmişi önerisi, daire bazında hesaplanan bakiye, düzenleme, onay ve dönem kilidi.
- **Raporlar:**
  - Pano.
  - Takip Excel'i düzeninde **tahsilat çizelgesi** (renkli).
  - Borçlu listesi (yaşlandırma).
  - Daire hesap ekstresi.
  - Mutabakat.
  - Excel çıktıları.
  - Denetim kaydı.
- **Kullanıcılar:** `admin` / `operator` / `viewer` rolleri, site bazında yetki.

## Yerel geliştirme

Gereksinimler: Python 3.10+, Node 20+ ([uv](https://github.com/astral-sh/uv) önerilir).

```bash
cd backend
uv venv .venv && uv pip install --python .venv -e ".[dev]"
.venv/Scripts/python run_dev.py        # Linux/macOS: .venv/bin/python run_dev.py
```

`run_dev.py` migration'ları uygular ve API'yi `http://localhost:8000` adresinde başlatır. Varsayılan veritabanı
`backend/data/aidat.db` (SQLite) dosyasıdır. İlk çalıştırmada `admin@ortabahce.local` / `admin123` yöneticisi
oluşturulur; bunu `backend/.env` ile değiştirin (bkz. `backend/.env.example`).

```bash
cd frontend
npm install
npm run dev                             # http://localhost:5173 (/api → 8000'e yönlenir)
```

Testler:

```bash
cd backend
.venv/Scripts/python -m pytest
```

Gerçek veriyle uçtan uca test (`tests/test_private_gulfa.py`), `backend/tests/fixtures/private/` klasöründeki
`takip_gulfa.xlsx` ve `ziraat_gulfa_2026.xlsx` dosyalarını kullanır. Dosyalar yoksa test atlanır. Bu klasör KVKK
gereği `.gitignore` ile repoya dahil edilmez.

## Üretim (Docker)

```bash
cp .env.example .env    # şifreleri ve SECRET_KEY'i doldurun
docker compose up -d --build
```

Uygulama `http://localhost:8080` adresinde açılır. Veritabanı olarak PostgreSQL 16 kullanılır; API açılışta
`alembic upgrade head` çalıştırır.

## Yeni bir siteyi devreye alma

1. **Siteler → Takip Excel'inden** (ya da **Yeni site** ile elle):
   - Kesim ayını banka ekstresinin başladığı ay yapın.
   - Önizlemede blokları, sakinleri ve yıl tahminini kontrol edin.
2. **Site ayarları → Bloklar ve takma adlar:** Sakinlerin açıklamada kullandığı farklı yazımları ekleyin.
3. **Açılış bakiyesi:**
   - Önerilen tarifeleri ekleyin.
   - Gerekirse oda tipine göre tarifeleri tanımlayın (Daireler → oda tipi ata; Tarife ve tahakkuk → oda tipi tarifesi).
   - Sonradan teslim edilen dairelerin başlangıç ayını düzeltin.
   - Bakiyeleri gözden geçirip **Onayla ve kilitle**.
4. **Tarife ve tahakkuk:** Kesimden bugüne aylık tahakkukları oluşturun.
5. **Ekstre yükle:** Bankadan indirilen Excel'i bırakın. Otomatik eşleşmeyenler **İnceleme kuyruğu**na düşer.
6. İncelemede onayladıkça sistem göndericileri öğrenir. Sonraki ekstrelerde kuyruk küçülür.

## Proje yapısı

```
backend/app/
  models/                SQLAlchemy modelleri (site, daire, kişi, defter, banka, denetim)
  services/
    xlsx/reader.py       stil hatasına dayanıklı xlsx okuyucu (calamine + ham XML yedeği)
    bank_parsers/        banka ekstresi ayrıştırıcıları (eklenti yapısı; ilk: Ziraat)
    dedup.py             tekrar anahtarı ve bakiye zinciri kontrolü
    matching/            normalize, daire/dönem/kategori çıkarımı, skorlama, öğrenme, OpenRouter
    legacy_import/       takip Excel'i ayrıştırıcı
    ledger.py            tarife, tahakkuk, bakiye, yaşlandırma
    opening_balance.py   açılış bakiyesi sihirbazı
    imports.py           ekstre ve takip Excel'i içe aktarma akışları
    reports/             çizelge, borçlular, mutabakat, pano, Excel çıktıları
  api/routes/            FastAPI uç noktaları
frontend/src/pages/      Pano, İnceleme, Çizelge, Daireler, Borçlular, İşlemler, Ekstre yükle,
                         Tarife ve tahakkuk, Açılış bakiyesi, Site ayarları, Siteler
```

## Yeni banka formatı ekleme

`backend/app/services/bank_parsers/` altına `BankParser` sınıfından türeyen bir sınıf ekleyin (`detect` ve
gerekiyorsa `parse`) ve `register()` ile kaydedin. Başlıkları standart olan bankalar için genel ayrıştırıcı zaten
çalışır.
