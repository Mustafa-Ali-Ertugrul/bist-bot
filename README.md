# BIST Bot — Borsa İstanbul Sinyal Botu

BIST hisselerini teknik indikatörlerle tarayan, sinyal üreten, Telegram'a bildiren, paper trade kaydı tutan ve backtest yapabilen otonom bir bot.

> **Ürün durumu (2026-10-21):** Sinyal botu müşteriye satılan bir ürün değil, iç araştırma aracıdır. Müşteri Telegram grubuna al/sat mesajı gönderilmez (`TELEGRAM_GROUP_ENABLED` varsayılan `false`); sinyal sayfaları ve API'leri yalnızca admin rolüne açıktır. Ücretli abonelik satışı kapalıdır. Yerine tarama, hisse analizi, izleme listesi ve alarmlar sunan bir analiz uygulaması geliştiriliyor.

## Özellikler

- RSI, MACD, Bollinger, SMA, EMA, ADX, Stochastic, CCI, OBV ve divergence tabanlı analiz
- 7 kademeli sinyal üretimi: GÜÇLÜ AL → AL → ZAYIF AL → BEKLE → ZAYIF SAT → SAT → GÜÇLÜ SAT
- Piyasa saatine duyarlı scheduler akışı
- Telegram bildirimleri ve sinyal değişim uyarıları
- Paper trade kaydı ve portfoy takibi
- Flask dashboard, Streamlit arayüz ve backtest araçları
- `pytest` ve `ruff` ile test/lint akışı

### Sinyal Türleri

- 💰 GÜÇLÜ AL : Skor ≥ 48
- 🟢 AL        : Skor ≥ 20
- 🟡 ZAYIF AL  : Skor ≥ 8
- ⚪ BEKLE     : -8 < Skor < 8
- 🟠 ZAYIF SAT : Skor ≤ -8
- 🔴 SAT       : Skor ≤ -20
- 🚨 GÜÇLÜ SAT : Skor ≤ -48

### Sinyal Yaşam Döngüsü

- Sinyallerin bir TTL (Time-To-Live) süresi vardır, `SIGNAL_TTL_MINUTES` ile kontrol edilir.
- Varsayılan TTL 60 dakikadır.
- Süresi dolmuş sinyaller geçmişte kalır ancak `is_expired=true` olarak işaretlenir.
- Telegram bildirimleri süresi dolmuş sinyalleri göndermez.
- `TELEGRAM_MIN_SCORE` varsayılanı `STRONG_BUY_THRESHOLD` ile eşlenmiştir (48).

## Mimari

- `main.py` bot runtime'ını başlatır; tarayıcıyı, scheduler'ı ve isteğe bağlı dashboard'u ayağa kaldırır.
- `src/bist_bot/scanner.py` çoklu zaman dilimi verisini toplar, `StrategyEngine` ile analiz eder, sinyalleri kaydeder ve bildirim yollar.
- `src/bist_bot/strategy/` skorlamayı, sinyal sınıflandırmasını ve risk yöneticisi entegrasyonunu yürütür.
- `src/bist_bot/risk/` stop, hedef, pozisyon boyutu, korelasyon ve sektor limitlerini yönetir.
- `src/bist_bot/db/` altındaki repository katmanı sinyal, konfigürasyon ve paper trade verilerini saklar.
- `dashboard.py` ve `streamlit_app.py` root'ta ince wrapper olarak kalir; asil uygulama kodu `src/bist_bot/` altindadir.

## Proje Yapısı

```text
bist_bot/
├── main.py                  # CLI wrapper
├── dashboard.py             # Flask wrapper
├── streamlit_app.py         # Streamlit wrapper
├── src/
│   └── bist_bot/
│       ├── main.py          # Ana CLI logic
│       ├── scanner.py       # Tarama orkestrasyonu
│       ├── scheduler.py     # Piyasa saati dongusu
│       ├── backtest.py      # Backtester ve yardimcilar
│       ├── dashboard.py     # Flask dashboard uygulamasi
│       ├── config/          # Runtime config ve UI preference store
│       ├── data/            # Veri fetcher kodu ve statik ticker listeleri
│       ├── db/              # Veritabani modelleri ve repository katmani
│       ├── execution/       # Broker/paper execution arayuzleri
│       ├── risk/            # Risk domain modulleri
│       ├── services/        # Scan side-effect servisleri
│       ├── strategy/        # StrategyEngine, scoring ve signal modelleri
│       └── ui/              # Streamlit runtime, sayfalar ve bilesenler
├── data/                    # Backtest ve veri ciktilari
├── tests/                   # Pytest test paketi
├── requirements.txt
└── dev-requirements.txt
```

## Kurulum

```bash
git clone https://github.com/Mustafa-Ali-Ertugrul/docmind-ai.git
cd docmind-ai
pip install -r requirements.txt
```

Ortam degiskenleri icin `.env.example` dosyasini baz alarak `.env` olusturabilirsiniz:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
ADMIN_BOOTSTRAP_EMAIL=admin@bistbot.local
ADMIN_BOOTSTRAP_PASSWORD_HASH=<scrypt_hash>
INITIAL_CAPITAL=100000
```

Onemli notlar:

- Eski `ADMIN_EMAIL` ve `ADMIN_PASSWORD_HASH` env adlari okunmaz; sadece `ADMIN_BOOTSTRAP_EMAIL` ve `ADMIN_BOOTSTRAP_PASSWORD_HASH` kullanilir.
- `TELEGRAM_MIN_SCORE` varsayilan olarak `STRONG_BUY_THRESHOLD` ile hizalanmistir; varsayilan esik `48`'dir.
- Kalici/uzak veritabani (PostgreSQL) kullaniminda `DATABASE_URL` tercih edin; lokal SQLite fallback icin `DB_PATH` kullanilabilir.

## Kullanım

Desteklenen giriş noktaları üç net role ayrılır:

- `main.py`: bot runtime'ı, scheduler ve isteğe bağlı gömülü Flask dashboard
- `streamlit_app.py`: operatör odaklı Streamlit arayüz
- `dashboard.py`: sadece standalone Flask dashboard süreci

```bash
python main.py                             # Varsayilan gelistirme akisi: bot + scheduler + Flask dashboard
python main.py --once                      # Tek tarama
python main.py --backtest                  # Watchlist icin backtest calistirir
python main.py --dashboard                 # Sadece Flask dashboard
python main.py --worker                    # Sadece scanner/scheduler worker
streamlit run streamlit_app.py             # Streamlit operator paneli
python dashboard.py                        # Standalone Flask dashboard (opsiyonel)
python -m bist_bot.backtest_compare --tickers THYAO.IS ASELS.IS
python scripts/benchmark_backtest.py       # Iterative vs vectorized benchmark
```

### Lokal araclar ve Docker Postgres

`.env` icindeki `DATABASE_URL`, Docker network icindeki `postgres` hostname'ini
kullanir; bu adres sadece konteynerlarin icinden cozumlenir. Host uzerinde
calisan lokal araclar (rapor uretimi, backfill scriptleri vb.) ayni
Postgres'e `localhost:5432` uzerinden erisebilir. `.env` dosyasini
degistirmeden, sadece o surec icin override edin:

```powershell
# PowerShell
$env:DATABASE_URL = "postgresql+psycopg2://bist:bist@localhost:5432/bist_bot"
python main.py --daily-report 2026-08-25
```

```bash
# bash
DATABASE_URL="postgresql+psycopg2://bist:bist@localhost:5432/bist_bot" \
  python main.py --daily-report 2026-08-25
```

Alternatif olarak ayni komutu konteyner icinde calistirabilirsiniz
(Docker network icinde `postgres` hostname'i gecerlidir):

```bash
docker exec bist-bot-worker python main.py --daily-report 2026-08-25
```

## Docker Compose

- `docker-compose.yml` servis bazli yapidadir:
  - `flask-api` -> Flask JSON API (`5000`)
  - `streamlit-ui` -> Streamlit operator UI (`8501`)
  - `scanner-worker` -> scheduler/scanner worker
- Ortak image `Dockerfile` ile uretilir; local script kullanimi degismez.
- Ortak veri `./data` volume'u uzerinden paylasilir, SQLite DB burada tutulur.
- `./secrets` klasoru read-only olarak `/run/secrets` altina mount edilir; hassas degerler icin `*_FILE` env deseni desteklenir.

```bash
docker compose up --build
```

Daha guvenli lokal kurulum ornegi:

```bash
mkdir -p secrets
printf 'replace-with-long-random-secret' > secrets/jwt_secret_key
printf 'telegram-token' > secrets/telegram_bot_token
docker compose up --build
```

- Compose icinde `JWT_SECRET_KEY` bos birakilabilir; uygulama otomatik olarak `JWT_SECRET_KEY_FILE=/run/secrets/jwt_secret_key` dosyasini okur.
- Ayni desen `TELEGRAM_BOT_TOKEN_FILE`, `ALGOLAB_PASSWORD_FILE`, `OFFICIAL_PASSWORD_FILE` icin de gecerlidir.
- Secret dosyalari repoya eklenmemelidir; `secrets/` klasoru `.gitignore` altindadir.

- UI: `http://localhost:8501`
- API health: `http://localhost:5000/health`

Healthcheckler:
- `flask-api` -> `/health`
- `streamlit-ui` -> `/_stcore/health`
- `scanner-worker` -> container ana prosesi (`kill -0 1`)

Backtest JSON ciktilari `data/` altina yazilir.

## Cloud Run (EMEKLİ — 2026-09-23)

Cloud Run deploy yolu **kaldırıldı**: `deploy-cloud-run.yml` workflow'u, `cloudrun/`
manifestleri ve `deploy.ps1` repodan silindi. Gerekçe: GCP projesinin faturalandırması
kapalıydı, deploy'lar 12 Eylül'den beri başarısızdı ve servis 503 dönüyordu.

- Desteklenen dağıtım yolu: **Docker Compose** (yukarıdaki bölüm).
- Uzak veritabanı gerekiyorsa `DATABASE_URL` hâlâ desteklenir (PostgreSQL bağlantı
  string'i compose servislerine verilebilir); `DB_PATH` SQLite fallback olarak kalır.
- `TRUSTED_PROXY_HOPS` ayarı kodda durur ve **her yerde 0 kalmalıdır** (AppSec
  Finding #21 Layer 2, bkz. `docs/security/rate_limit_ip_collapse_finding21.md`).
  Ters proxy arkasına geri dönülürse canlı X-Forwarded-For doğrulaması yapmadan
  1 YAPILMAZ.

## Official Data Provider

`DATA_PROVIDER=official` ile Matriks, Foreks, Finnet gibi resmi veri saglayicilara baglanabilirsiniz. Provider, endpoint mapping'i uzerinden genisletilebilir bir REST adapter yapisi sunar.

### Yapilandirma

```env
DATA_PROVIDER=official
OFFICIAL_VENDOR=matriks
OFFICIAL_API_BASE_URL=https://api.matriks.com
OFFICIAL_API_KEY=your_api_key
OFFICIAL_USERNAME=your_username
OFFICIAL_PASSWORD=your_password
OFFICIAL_TIMEOUT=30
OFFICIAL_MAX_RETRIES=3
OFFICIAL_RETRY_BACKOFF_SECONDS=1

# Gerekirse vendor endpoint'lerini override edin
OFFICIAL_AUTH_ENDPOINT=
OFFICIAL_HISTORY_ENDPOINT=
OFFICIAL_BATCH_ENDPOINT=
OFFICIAL_QUOTE_ENDPOINT=
OFFICIAL_UNIVERSE_ENDPOINT=
```

### Vendor-Specific Adapter

Endpoint path'leri `OfficialProviderEndpoints` uzerinden override edilir:

```python
from bist_bot.data.providers import OfficialProvider, OfficialProviderEndpoints

class MatriksProvider(OfficialProvider):
    endpoints = OfficialProviderEndpoints(
        auth="/matriks/v1/auth",
        history="/matriks/v1/ohlcv",
        batch="/matriks/v1/ohlcv/batch",
        quote="/matriks/v1/quote",
        universe="/matriks/v1/symbols",
    )
```

- Varsayilan: `yfinance` (degisiklik yok)
- `official_stub`: test amacli bos stub
- `official`: gercek REST adapter (yukaridaki env'ler gerekli)
- `OFFICIAL_VENDOR`: `generic`, `matriks`, `foreks`, `finnet`
- Timeout, retry ve rate limit destegi dahildir
- 401/429/5xx otomatik retry; 4xx hemen hata firlatir

## Test & Lint

```bash
export PYTHONPATH=src  # Windows'ta esdegeri: set PYTHONPATH=src
pytest tests/ -v
ruff check . --isolated
```

## Gün Sonu Piyasa Verisi (Faz 1)

Tarayıcı ve hisse sayfalarının temeli olan gün sonu veri deposu. Canlı 15 dakikalık tarama yolundan ayrıdır; bir veri kaynağı hatası pozisyon kapatmayı etkilemez.

- `instruments`: BIST pay evreni (kod, ad, sektör). Liste koda gömülü değildir, sağlayıcıdan yenilenir.
- `daily_bars`: `(ticker, date)` anahtarlı OHLCV. `close` bedelsiz/bölünme düzeltmeli (`HGDG_KAPANIS`), `close_raw` ham kapanış (`HG_KAPANIS`). Açılış fiyatı kaynakta yok, `open` boş kalır.
- `fundamentals`: çeyreklik bilanço kalemleri (`2O`, `3Z`, `3C`).

Varsayılan olarak kapalıdır (`DAILY_BARS_ENABLED=false`). Önce yerelde doldurup raporu inceleyin:

```bash
python scripts/backfill_market_data.py --limit 5 --start 2024-01-01
python scripts/backfill_market_data.py --symbols THYAO,GARAN --fundamentals
python scripts/backfill_market_data.py --refresh-universe
python scripts/backfill_market_data.py --incremental
```

Rapor JSON'dur: `symbols`, `written`, `failed`, `empty`, `elapsed_seconds`, `errors`. Aynı pencere ikinci kez yazılınca satır sayısı artmaz (idempotent).

Açıldığında worker, seans kapanışından sonra günde bir kez yalnızca eksik günleri çeker. İlk çalıştırmada geçmiş yoksa `DAILY_BARS_INITIAL_LOOKBACK_DAYS` kadar geriye bakar; tüm geçmişi doldurmak backfill script'inin işidir.

## Gün Sonu Taramaları (Faz 2)

`daily_bars` üzerinde çalışan tarama kütüphanesi (`strategy/scans.py`). Her tarama saftır: yalnızca `as_of` gününe kadarki barları ve o tarihte yayımlanmış çeyrekleri görür. Canlı 15 dakikalık `StrategyEngine` kullanılmaz.

| Kod | Kural |
|---|---|
| `rsi_dip` | RSI(14) < 30 |
| `sma_5_22` | SMA5, SMA22'yi yukarı keser |
| `sma_50_200` | SMA50, SMA200'ü yukarı keser |
| `hacim_sok` | Hacim, 20 günlük ortalamanın ≥2 katı |
| `zirve_52h` | Kapanış, önceki 252 günün zirvesini geçer (bugün hariç) |
| `bb_sikisma` | Bollinger genişliği son 120 günün en dar %10'unda |
| `ucuz_karli` | Yayımlanmış son yıl net kârı > 0 ve F/K ≤ 10 |
| `satis_buyume` | Son yayımlanmış çeyrekte satışlar yıllık ≥ %20 artmış |

- Yetersiz geçmişte tarama ateşlemez (`MIN_BARS`): 5-22 için 23 bar, 50-200 için 201 bar.
- Sonuçlar `scan_results` tablosuna yazılır: `(scan_id, as_of, ticker)` tekildir; aynı gün yeniden çalışmak satır çoğaltmaz, eski günler korunur.
- Varsayılan kapalı: `SCREEN_SCANS_ENABLED=false`. Açıldığında worker, gün sonu veri eklendikten sonra günde bir kez çalışır. **Müşteriye mesaj göndermez.**
- Temel taramalar `SCREEN_FUNDAMENTAL_SCANS_ENABLED` ile ayrıca kapatılabilir.

## Hisse Sayfası (Faz 3)

`/ui/stock/<kod>`: tek hissede fiyat grafiği, getiriler, teknik özet, temel oranlar, çeyreklik tablo ve son 30 günün tarama geçmişi. Tüm veri depodan gelir; sayfa dışarıya istek atmaz.

- API: `GET /api/stocks/search?q=`, `/api/stocks/<kod>`, `/api/stocks/<kod>/bars?range=1m|3m|1y|5y|all`, `/api/stocks/<kod>/fundamentals`, `/api/stocks/<kod>/scans?days=30`.
- Erişim varsayılan olarak yalnızca admin (`STOCK_PAGES_PUBLIC=false`). Açmak, lisanssız sağlayıcı verisini üyelere göstermek demektir; lisanslı veriye geçmeden açılmamalı.
- Grafik: yerelleştirilmiş TradingView Lightweight Charts v5 (`static/vendor/`, Apache-2.0, atıf logosu açık). CSP satır içi script'e izin vermediği için CDN kullanılmaz.
- Mum grafiği yok: kaynakta açılış fiyatı yok, uydurulmaz. Düzeltilmiş kapanış çizgisi ve hacim gösterilir.
- Oranlar: F/K ve net marj son 12 ay (TTM) üzerinden; PD/DD son özkaynak; negatif kârda F/K boş.
- Taramalardaki F/K yıllık Aralık kârıdır, sayfadaki F/K TTM'dir; etiketler bunu ayırır.
- KAP, temettü ve sermaye artırımı verisi bu fazda yok; boş bölüm gösterilmez.

## Tarayıcı (Faz 4)

`/ui/screener`: hazır taramaların sonuçları, geçmiş seanslar ve kullanıcının kendi filtresi. Her satır hisse sayfasına bağlanır.

- Hazır taramalar `scan_results` tablosundan gelir; her taramanın açıklaması ve o günkü sonuç sayısı gösterilir.
- Kendi filtresi `screen_snapshots` tablosunu okur: her seansta hisse başına tek satır (getiriler, RSI, SMA uzaklıkları, 52 hafta zirvesi, hacim, piyasa değeri, F/K, PD/DD, marj, ROE, satış büyümesi).
- Alanlar ve operatörler beyaz listededir; kullanıcı metni SQL'e girmez. En fazla 10 koşul; sektör ve tarama filtresi.
- API: `GET /api/screens`, `/api/screens/fields`, `/api/screens/<kod>`, `POST /api/screener/query`.
- Erişim hisse sayfasıyla aynı kapıyı kullanır (`STOCK_PAGES_PUBLIC`). Ücretli olmayan üyeler sunucuda `SCREENER_FREE_LIMIT` kadar satır görür; tam liste tarayıcıya hiç gitmez.
- Filtre kaydetme ve CSV dışa aktarma yok; filtre kaydı Faz 6'daki alarmlarla gelecek.

## İzleme Listesi ve Portföy (Faz 5)

- `/ui/watchlist`: kişisel listeler (en fazla 5 liste × 100 hisse), tarayıcıdaki özet kolonlarıyla.
- `/ui/portfolio`: elle girilen işlemler (en fazla 3 portföy × 500 işlem), pozisyonlar, ortalama maliyet, gerçekleşmiş/gerçekleşmemiş K/Z ve kıyas grafiği.
- Tablolar botun kendi tablolarından ayrıdır: `user_watchlists`, `user_watchlist_items`, `user_portfolios`, `user_portfolio_transactions`. Kullanıcı silinince kayıtlar da silinir.
- **Bedelsiz/bölünme:** adetler düzeltilmiş birimle tutulur (`adet × ham fiyat / düzeltilmiş fiyat`), böylece bedelsiz sahte zarar üretmez. Satışta da aynı dönüşüm kullanılır.
- **Kıyas:** aynı nakit akışı XU100'e ve para piyasasına uygulanır. XU100, İş Yatırım satırlarındaki endeks kolonundan (`END_ENDEKS_KODU=01`) `benchmark_bars` tablosuna yazılır (`BENCHMARK_PROXY_TICKER=THYAO`).
- Para piyasası: TEFAS uç noktası doğrulanamadığı için varsayılan olarak **tanımsızdır**. `MONEY_MARKET_ANNUAL_RATE_PCT` verilirse bileşik faiz varsayımıyla hesaplanır ve ekranda "varsayım" olarak etiketlenir.
- API: `/api/watchlists`, `/api/portfolios`, `/api/portfolios/<id>/transactions`. Sahiplik ihlali 403 değil 404 döner.
- Erişim hisse sayfasıyla aynı kapı (`STOCK_PAGES_PUBLIC`).

## Alarmlar ve Akşam Özeti (Faz 6)

- `/ui/alerts`: Telegram bağlantısı, alarm listesi, kayıtlı filtreler ve göndermeden önce özet önizlemesi.
- **Bağlama:** Web'de tek kullanımlık, 15 dakikalık bir bağlantı üretilir; DB'de yalnızca SHA-256 özeti tutulur. Kullanıcı `t.me/<bot>?start=<jeton>` bağlantısına basınca worker'daki `getUpdates` döngüsü `/start` mesajını işler. Yalnızca özel sohbetler kabul edilir. `/stop` bağlantıyı kaldırır. Okuma konumu `app_settings` içinde tutulur.
- **Alarmlar:** hazır tarama takibi (isteğe bağlı "sadece izleme listem"), kayıtlı filtreye yeni girenler, tek seferlik fiyat seviyesi ve günlük değişim eşiği. Hepsi kapanış verisiyle çalışır.
- **Özet:** Taramalar bittikten sonra günde bir, kullanıcı başına tek mesaj. `user_digest_log` `(user_id, as_of)` ile çift gönderim engellenir. O gün tetiklenen bir şey yoksa mesaj gitmez. Mesaj 3.900 karaktere kısaltılır ve HTML'den kaçırılır.
- **Kimlik:** `TELEGRAM_USER_BOT_TOKEN` / `TELEGRAM_USER_BOT_USERNAME`; token yoksa operatör token'ına düşer. Operatör uyarılarıyla karışmaması için ayrı bot önerilir.
- Varsayılan kapalı: `TELEGRAM_LINK_POLLING_ENABLED=false`, `USER_DIGEST_ENABLED=false`. `USER_DIGEST_HOUR_TR` (varsayılan 18) özetin en erken saatidir; scheduler seans sonunda çalıştığı için 20:00 gibi geç bir saat özeti kaçırır.
- Bu faz müşteriye kendiliğinden mesaj gönderen ilk parçadır; onaysız deploy edilmez.

## Ticari Hazırlık (Faz 7)

**Kod tarafı tamamlananlar**
- Hukuk metinleri taslak olarak uygulamada: `/legal/kullanim-kosullari`, `/legal/gizlilik`, `/legal/kvkk-aydinlatma`, `/legal/mesafeli-satis`. `LEGAL_TEXTS_DRAFT=true` iken sayfada "TASLAK" bandı görünür.
- Kayıt ekranında onay kutusu; kabul edilen her belgenin sürümü `legal_acceptances` tablosuna yazılır.
- KVKK hakları: `GET /api/me/export` (şifre özeti hariç tüm kişisel veriler) ve `POST /api/me/delete` (şifre doğrulamalı, kişisel tabloları CASCADE ile siler, oturumu kapatır).
- Paket hakları tek yerde: `services/entitlements.py` (ücretsiz/deneme ve ücretli limitleri; admin sınırsız).
- Veri kaynağı soyutlaması: `data/market_source.py`. `MARKET_DATA_SOURCE` ile lisanslı adaptör takılır; bilinmeyen kaynak açık hata verir.
- `DATA_PUBLIC_SERVING_ENABLED=false` veri yayınını admin dışına kapatır (lisans biterse kill switch). Sayfalarda `DATA_ATTRIBUTION` satırı gösterilir.

**Kod tarafı bilerek açılmayanlar (dış hesap gerekiyor)**
- Kartla ödeme ve tekrarlı abonelik: iyzico/PayTR hesabı, şirket/vergi levhası ve e-Arşiv fatura düzeni olmadan yazılan entegrasyon test edilemez. Bu yüzden ödeme kodu bu turda yazılmadı; mevcut elle EFT akışı kapalı kalıyor.
- Lisanslı veri adaptörü: sağlayıcı sözleşmesi ve API dokümanı olmadan uç nokta tahmin edilmez.
- Avukat onayı: metinler taslak; satış öncesi zorunlu.

**Borsa İstanbul veri lisansı (araştırma notu)**
- Dağıtıcı olmak için BIST ile Veri Dağıtım Sözleşmesi gerekir; tarifede ilk teknik bağlantı 25.000 TL, yıllık teknik bağlantı 112.500 TL ve ürün ücretleri var.
- Alternatif: yetkili bir dağıtıcı (Matriks, Foreks, İdeal vb.) üzerinden alt dağıtıcı olmak.
- BIST, veriden türetilen analizlerin de sözleşme kapsamında olduğunu belirtiyor. Kesin kapsam ve dönem sözleşme ekinde.

## Tarama Karnesi (Faz 8a)

`/ui/scorecard`: her hazır taramanın sinyal verdiği günlerde sonraki 5 / 20 / 60 işlem gününde ne getirdiğini gösterir.

- Aynı günlerde iki kıyas: **XU100** ve **sabit rastgele 20 hisse** sepeti (tarama başına belirlenimci, tekrar üretilebilir).
- Getiri düzeltilmiş kapanıştan; işlem maliyeti düşülmemiş.
- **Kanıt eşiği:** en az 30 gözlem ve |t| ≥ 2. Altındaki satırlar "yetersiz veri" yazar. Bu, kendi ligimizdeki Bonferroni disipliniyle aynı çizgide.
- API: `GET /api/scores?since=&horizons=` ve `GET /api/scores/<kod>`.
- Veri yoksa tarama "kayıtlı sonuç yok" olarak listelenir; uydurma sayı üretilmez.
- Yeni veri biriktikçe karne kendiliğinden güncellenir; ayrı bir job gerekmez.

## Historical Universe

- Point-in-time universe snapshot'lari `src/bist_bot/data/universe/` altinda JSON olarak tutulur.
- `bist_bot.data.universe.get_universe_for_date(date)` ilgili tarih icin en yakin gecmis snapshot'i cozer.
- Snapshot bulunamazsa sistem warning log atar ve mevcut `WATCHLIST`/current universe'e geri doner.
- Backtest ve walk-forward icin opsiyonel kullanim:

```bash
python main.py --backtest --historical-universe-date 2024-01-01
python main.py --backtest --walk-forward --historical-universe-date 2023-01-01
```

- Varsayilan `Backtester` akisi, ozel `signal_builder` yoksa vectorized path kullanir.
- `signal_builder` tanimliysa backtest iterative fallback'e duser; cunku sinyal uretimi bar-bazli ozel mantiga bagli olabilir.
- Intrabar stop/target cikislari davranis esitligini korumak icin trade bazli sirali degerlendirilir; bu kisim tamamen toplu hale getirilmemistir.

## Import Migration (Shim Cleanup)

Legacy shim dosyalari kaldirildi. Asagidaki eski importleri yeni pathlere tasiyin:

| Eski Import | Yeni Import |
|---|---|
| `from bist_bot.risk_manager import RiskManager, RiskLevels` | `from bist_bot.risk import RiskManager, RiskLevels` |
| `from bist_bot.database import SignalDatabase` | `from bist_bot.db import DataAccess` |

- `bist_bot.risk_manager` artik kaldirildi; `RiskManager` ve `RiskLevels` dogrudan `bist_bot.risk` icinden import edilmelidir.
- `bist_bot.database` tamamen kaldirildi; `DataAccess` dogrudan `bist_bot.db`'den import edilmelidir.

## Known Limitations

- **Survivorship bias**: `yfinance` verisi delisted hisseleri her zaman icermeyebilir; backtest ve walk-forward sonuclarinda survivorship bias olasıdır.
- **Point-in-time universe coverage**: Ilk surum snapshot tabanlidir; tum tarihleri kapsamaz. Snapshot olmayan tarihlerde sistem warning ile current universe'e fallback yapar.
- **Intraday gecikme**: BIST verileri 15 dakika gecikmeli sunulur; gerçek zamanli emirde fiyat farkı oluşabilir.
- **Rate limit**: yfinance ve BIST scraper için rate limit mevcuttur; coklu isteklerde 429 donusu alınabilir.

## Security

- Flask API JWT tabanli auth ile korunur; startup icin yalnizca `JWT_SECRET_KEY` zorunludur.
- Kimlik dogrulama tek kaynak olarak `users` tablosundan yapilir; login endpoint env icindeki admin bilgilerini dogrudan kullanmaz.
- `ADMIN_BOOTSTRAP_EMAIL` ve `ADMIN_BOOTSTRAP_PASSWORD_HASH` verilirse bunlar sadece bootstrap icin kullanilir: uygulama ilk acilista `users` tablosu bossa ilk admin kullanicisi olusturulur.
- `users` tablosunda en az bir kullanici varsa env bootstrap ayarlari yok sayilir; mevcut DB kullanicilari source of truth olmaya devam eder.
- CORS sadece `CORS_ORIGINS` whitelist'inden gelen origin'lere izin verir; `*` varsayilan olarak kullanilmaz.
- Flask-Limiter varsayilan olarak `memory://` kullanir. Uretimde ve multi-worker deployment'larda `RATE_LIMIT_STORAGE_URI=redis://...` gibi paylasimli bir backend kullanin.
- Uretimde `.env` dosyasini repoya eklemeyin; hassas ayarlar ortam degiskenleri veya lokal `.env` ile saglanmalidir.
- Secret-bearing env'ler icin mumkunse dogrudan `*_FILE` kullanin; ornek: `JWT_SECRET_KEY_FILE`, `TELEGRAM_BOT_TOKEN_FILE`, `ALGOLAB_PASSWORD_FILE`, `OFFICIAL_PASSWORD_FILE`.
- Lokal depoda gercek token/anahtar varsa bunlari rotate etmek en guvenli secenektir; `.gitignore` tek basina daha once izlenmis secret'lari korumaz.

Migration note:

- Eski davranista env admin bilgileri startup icin zorunluydu; artik degil. Mevcut deployment'ta `users` tablosunda kullanici varsa ekstra degisiklik gerekmez.
- Yeni kurulumda isterseniz ilk admin kullanicisini bir kez `ADMIN_BOOTSTRAP_EMAIL` + `ADMIN_BOOTSTRAP_PASSWORD_HASH` ile bootstrap edin; tablo dolduktan sonra bu env'leri kaldirabilirsiniz.
- Eski `ADMIN_EMAIL` ve `ADMIN_PASSWORD_HASH` env adlari artik okunmaz; deployment env'lerini yeni bootstrap adlarina tasiyin.

## Observability

- `LOG_FORMAT=json` ayari ile loglar JSON olarak akar; varsayilan `console` modu lokal gelistirmede daha okunaklidir.
- `LOG_LEVEL=INFO` veya `DEBUG` ile detay seviyesi ayarlanabilir.
- Flask API `GET /metrics` endpoint'i uzerinden JWT auth ile Prometheus text format metrikler sunar.
- Lokal gozlemlenebilirlik araclari (Grafana 3000, Prometheus 9090, Postgres 5432) varsayilan olarak yalnizca `127.0.0.1` uzerine bind edilir; uzaktan erisim icin SSH tunnel kullanin:

```bash
ssh -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 kullanici@sunucu
```
- Metrik katmani thread-safe tutulur; `prometheus_client` mevcutsa resmi registry/exporter kullanilir, degilse uyumlu fallback registry devreye girer.

## Streamlit Cooldown

- Streamlit UI, oturum bazli hafif cooldown uygular; bu katman Flask rate limiter'in yerine gecmez, sadece UI tarafli asiri scan/analyze tetiklemelerini azaltir.
- Ayarlar:
  - `STREAMLIT_SCAN_COOLDOWN_SECONDS`
  - `STREAMLIT_ANALYZE_COOLDOWN_SECONDS`
- Cooldown'a takilan kullaniciya UI icinde "Cok sik istek gonderildi, birkac saniye bekleyin" mesaji gosterilir.

Ornek:

```bash
LOG_FORMAT=json python main.py --worker
curl -H "Authorization: Bearer <token>" http://localhost:5000/metrics
```

## Live Trading (Experimental)

- `BROKER_PROVIDER=algolab` ile AlgoLab broker iskeleti secilebilir; ancak resmi HTTP endpoint yollarinin guncelligi teyit edilmeden canli kullanim yapmayin.
- AlgoLab tarafinda sandbox/mock HTTP akislari ile emir, iptal, durum sorgusu ve kimlik dogrulama adimlarini dogrulamadan `ALGOLAB_DRY_RUN=false` kullanmayin.
- `DATA_PROVIDER=matriks|foreks|finnet` secenekleri icin de ayni ilke gecerlidir; endpoint path'leri ve rate-limit davranisi teyit edilmeden canli veri veya trade otomasyonu acmayin.
- `ALGOLAB_DRY_RUN=true` varsayilan ve onerilen moddur; bu modda emirler sadece loglanir, gercekten gonderilmez.
- Canli emir icin cift onay gerekir: `ALGOLAB_DRY_RUN=false` ve `CONFIRM_LIVE_TRADING=true` birlikte ayarlanmalidir.
- `AUTO_EXECUTE` varsayilan olarak kapali gelir; acildiginda ilk asamada yalnizca `STRONG_BUY` ve `STRONG_SELL` sinyalleri broker'a iletilir.
- Tum risk ve sorumluluk kullanicidadir; bu iskelet uretim oncesi broker sandbox/mock ortaminda ayrica dogrulanmalidir.

## Data Storage Roadmap

- Varsayilan kurulum SQLite ile basit tutulur; veri hacmi ve tarihsel saklama ihtiyaci buyudukce PostgreSQL + TimescaleDB gecisi planlanir.
- Gecis planinda migration sirasiyla su adimlar izlenmelidir: tablo/sema esleme, tarihsel backfill, retention/compression politikasi, indeksleme, dual-write dogrulamasi ve kontrollu cutover.

## Contributing

Please read [CONTRIBUTING.md](./CONTRIBUTING.md) before opening a PR or pushing non-trivial changes.

## Lisans

MIT
