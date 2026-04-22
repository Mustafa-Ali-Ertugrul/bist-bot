# BIST Bot — Borsa İstanbul Sinyal Botu

BIST hisselerini teknik indikatörlerle tarayan, sinyal üreten, Telegram'a bildiren, paper trade kaydı tutan ve backtest yapabilen otonom bir bot.

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
pip install -r requirements.txt
```

Ortam degiskenleri icin `.env.example` dosyasini baz alarak `.env` olusturabilirsiniz:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

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
```

## Docker Compose

- `docker-compose.yml` servis bazli yapidadir:
  - `flask-api` -> Flask JSON API (`5000`)
  - `streamlit-ui` -> Streamlit operator UI (`8501`)
  - `scanner-worker` -> scheduler/scanner worker
- Ortak image `Dockerfile` ile uretilir; local script kullanimi degismez.
- Ortak veri `./data` volume'u uzerinden paylasilir, SQLite DB burada tutulur.

```bash
docker compose up --build
```

- UI: `http://localhost:8501`
- API health: `http://localhost:5000/health`

Healthcheckler:
- `flask-api` -> `/health`
- `streamlit-ui` -> `/_stcore/health`
- `scanner-worker` -> container ana prosesi (`kill -0 1`)

Backtest JSON ciktilari `data/` altina yazilir.

## Test & Lint

```bash
export PYTHONPATH=src  # Windows'ta esdegeri: set PYTHONPATH=src
pytest tests/ -v
ruff check . --isolated
```

## Historical Universe

- Point-in-time universe snapshot'lari `src/bist_bot/data/universe/` altinda JSON olarak tutulur.
- `bist_bot.data.universe.get_universe_for_date(date)` ilgili tarih icin en yakin gecmis snapshot'i cozer.
- Snapshot bulunamazsa sistem warning log atar ve mevcut `WATCHLIST`/current universe'e geri doner.
- Backtest ve walk-forward icin opsiyonel kullanim:

```bash
python main.py --backtest --historical-universe-date 2024-01-01
python main.py --backtest --walk-forward --historical-universe-date 2023-01-01
```

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
- Uretimde `.env` dosyasini repoya eklemeyin; hassas ayarlar ortam degiskenleri veya lokal `.env` ile saglanmalidir.

Migration note:

- Eski davranista env admin bilgileri startup icin zorunluydu; artik degil. Mevcut deployment'ta `users` tablosunda kullanici varsa ekstra degisiklik gerekmez.
- Yeni kurulumda isterseniz ilk admin kullanicisini bir kez `ADMIN_BOOTSTRAP_EMAIL` + `ADMIN_BOOTSTRAP_PASSWORD_HASH` ile bootstrap edin; tablo dolduktan sonra bu env'leri kaldirabilirsiniz.
- Eski `ADMIN_EMAIL` ve `ADMIN_PASSWORD_HASH` env adlari artik okunmaz; deployment env'lerini yeni bootstrap adlarina tasiyin.

## Live Trading (Experimental)

- `BROKER_PROVIDER=algolab` ile AlgoLab broker iskeleti secilebilir; ancak resmi HTTP endpoint yollarinin guncelligi teyit edilmeden canli kullanim yapmayin.
- `ALGOLAB_DRY_RUN=true` varsayilan ve onerilen moddur; bu modda emirler sadece loglanir, gercekten gonderilmez.
- Canli emir icin cift onay gerekir: `ALGOLAB_DRY_RUN=false` ve `CONFIRM_LIVE_TRADING=true` birlikte ayarlanmalidir.
- `AUTO_EXECUTE` varsayilan olarak kapali gelir; acildiginda ilk asamada yalnizca `STRONG_BUY` ve `STRONG_SELL` sinyalleri broker'a iletilir.
- Tum risk ve sorumluluk kullanicidadir; bu iskelet uretim oncesi broker sandbox/mock ortaminda ayrica dogrulanmalidir.

## Contributing

Please read [CONTRIBUTING.md](./CONTRIBUTING.md) before opening a PR or pushing non-trivial changes.

## Lisans

MIT
