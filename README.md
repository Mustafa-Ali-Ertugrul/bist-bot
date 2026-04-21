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
- `scanner.py` çoklu zaman dilimi verisini toplar, `StrategyEngine` ile analiz eder, sinyalleri kaydeder ve bildirim yollar.
- `strategy.py` skorlamayı, sinyal sınıflandırmasını ve risk yöneticisi entegrasyonunu yürütür.
- `risk_manager.py` stop, hedef, pozisyon boyutu, korelasyon ve sektor limitlerini yönetir.
- `db/` altındaki repository katmanı sinyal, konfigürasyon ve paper trade verilerini saklar.
- `dashboard.py` Flask API/dashboard üretir; `streamlit_app.py` ise `ui/` bileşenleriyle interaktif arayuz sunar.

## Proje Yapısı

```text
bist_bot/
├── main.py                  # Ana CLI giris noktasi
├── scanner.py               # Tarama ve bildirim orkestrasyonu
├── scheduler.py             # Piyasa saati dongusu
├── strategy.py              # StrategyEngine ve sinyal skorlama
├── risk_manager.py          # Risk, korelasyon ve sektor limiti
├── indicators.py            # Teknik indikatör hesaplamalari
├── data_fetcher.py          # yfinance veri toplama ve cache
├── notifier.py              # Telegram bildirim katmani
├── backtest.py              # Backtester, StrategyBacktester, BacktestResult
├── backtest_runner.py       # CLI backtest akisi ve JSON ciktilari
├── backtest_compare.py      # Eski/yeni backtest karsilastirma araci
├── dashboard.py             # Flask dashboard uygulamasi
├── streamlit_app.py         # Streamlit arayuz giris noktasi
├── streamlit_utils.py       # Streamlit yardimci fonksiyonlari
├── dependencies.py          # Uygulama container kurulumlari
├── config/
│   ├── __init__.py          # `settings` export'u
│   └── settings.py          # Ana ayarlar ve override mekanizmasi
├── db/
│   ├── database.py          # Veritabani modelleri ve manager
│   └── repositories/        # Sinyal, portfoy ve config repository'leri
├── ui/
│   ├── runtime.py           # Streamlit runtime akisi
│   ├── components/          # Ortak UI bilesenleri
│   └── pages/               # Portfolio, Signals, Backtest, Settings sayfalari
├── execution/               # Broker/paper execution arayuzleri
├── data/                    # Veri ve backtest ciktilari
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
streamlit run streamlit_app.py             # Streamlit operator paneli
python dashboard.py                        # Standalone Flask dashboard (opsiyonel)
python backtest_compare.py --tickers THYAO.IS ASELS.IS
```

Backtest JSON ciktilari `data/` altina yazilir.

## Test & Lint

```bash
pytest tests/ -v
ruff check . --isolated
```

## Known Limitations

- `yfinance` verisi delisted hisseleri her zaman icermeyebilir; bu nedenle backtest ve walk-forward sonuclarinda survivorship bias olasi kalir.

## Security

- Flask API JWT tabanli auth ile korunur; `JWT_SECRET_KEY`, `ADMIN_EMAIL` ve `ADMIN_PASSWORD_HASH` olmadan API startup baslatilmaz.
- CORS sadece `CORS_ORIGINS` whitelist'inden gelen origin'lere izin verir; `*` varsayilan olarak kullanilmaz.
- Uretimde `.env` dosyasini repoya eklemeyin; hassas ayarlar ortam degiskenleri veya lokal `.env` ile saglanmalidir.

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
