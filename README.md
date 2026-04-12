# BIST Bot - Borsa Istanbul Sinyal Botu

Borsa Istanbul (BIST) hisse senetleri icin teknik analiz, skor bazli sinyal uretimi ve izleme akislari sunan otomasyon projesi.

Proje; 60+ hisseyi tarar, teknik gostergeleri puanlar, risk seviyelerini hesaplar ve sonuclari dashboard ya da Telegram uzerinden iletir.

## Hizli Baslangic

Python 3.10+ onerilir.

```bash
# 1. Repoyu klonla
git clone https://github.com/<kullanici>/bist_bot.git
cd bist_bot

# 2. Sanal ortam olustur
python -m venv venv

# Windows:
venv\Scripts\activate

# macOS/Linux:
source venv/bin/activate

# 3. Bagimliliklari yukle
pip install -r requirements.txt

# 4. Ortam degiskenlerini ayarla
copy .env.example .env          # Windows
# cp .env.example .env          # macOS/Linux

# .env dosyasini acip Telegram bilgilerini gir

# 5. Calistir
python main.py
```

## Giris Noktalari

Bu projede birden fazla calistirma modu var. Amacina gore birini sec:

| Komut | Ne Yapar |
|---|---|
| `python main.py` | Bot dongusunu baslatir + Flask dashboard (varsayilan mod) |
| `python main.py --once` | Tek seferlik tarama yapar ve cikar |
| `python main.py --backtest` | Tum watchlist uzerinde backtest calistirir |
| `python main.py --dashboard` | Sadece Flask dashboard'u baslatir (port 5000) |
| `streamlit run streamlit_app.py` | Streamlit dashboard (ana arayuz, port 8501) |
| `streamlit run mobile_app.py` | Mobil optimize Streamlit arayuzu |
| `python start_app.py` | Streamlit'i arka planda baslatir (Windows icin) |
| `python dashboard.py` | Flask API + dashboard'u tek basina calistirir |

**Onerilen kullanim:** Gunluk takip icin `streamlit run streamlit_app.py`, otomasyon icin `python main.py`.

## Ozellikler

- **Skor bazli sinyal motoru** — Her hisse icin -100 ile +100 arasi toplam skor hesaplanir
- **15+ teknik gosterge** — RSI, MACD, Bollinger, SMA/EMA, ADX, Stochastic, CCI, OBV, RSI/MACD Divergence, destek/direnc
- **Coklu sinyal seviyesi** — Guclu Al, Al, Zayif Al, Bekle, Zayif Sat, Sat, Guclu Sat
- **Risk yonetimi** — ATR, Fibonacci, destek/direnc, swing ve yuzdelik bazli stop-loss/hedef hesabi
- **Backtest** — Komisyon, BSMV ve kayma dahil gercekci backtest
- **Walk-forward optimizasyon** — RSI esik degerlerini otomatik optimize eder
- **ML fiyat tahmini** — GradientBoosting ile kisa vadeli fiyat tahmini
- **Telegram bildirimleri** — Guclu sinyallerde ve sinyal degisikliklerinde otomatik bildirim
- **Streamlit dashboard** — Canli tarama, grafik, gostergeler, haberler, filtreler
- **Flask API** — REST API ile sinyal sorgulama ve tarama
- **Mobil arayuz** — Mobil optimize edilmis Streamlit sayfasi
- **Android uygulamasi** — Kotlin/Jetpack Compose ile yerel Android uygulamasi (`android_app/`)
- **Paper trading** — Sanal islem modu ile strateji testi
- **Sektor limiti** — Ayni sektorden en fazla N hisse sinyali
- **SQLite veritabani** — Sinyal gecmisi, tarama loglari, paper trade kayitlari

## Strateji Nasil Calisir

Bot basit bir "RSI < 30 ise al" mantigi **kullanmaz**. Bunun yerine coklu gosterge skorlama sistemi vardir:

### Skorlama Tablosu

| Gosterge | Alim Skoru | Satim Skoru | Aciklama |
|---|---|---|---|
| RSI < 25 | +18 | — | Asiri satim |
| RSI < 30 | +14 | — | Satim bolgesi |
| RSI > 70 | — | -14 | Asiri alim |
| RSI > 80 | — | -18 | Guclu asiri alim |
| SMA Golden Cross | +12 | — | Kisa SMA uzun SMA'yi yukari kesti |
| SMA Death Cross | — | -12 | Kisa SMA uzun SMA'yi asagi kesti |
| EMA Bullish Cross | +10 | — | Hizli EMA yavas EMA'yi yukari kesti |
| EMA Bearish Cross | — | -10 | Hizli EMA yavas EMA'yi asagi kesti |
| MACD Bullish | +12 | — | MACD sinyal cizgisini yukari kesti |
| MACD Bearish | — | -12 | MACD sinyal cizgisini asagi kesti |
| MACD Histogram gucleniyor | +5 | — | Momentum artisi |
| ADX > 25 + DI yukari | +8 | — | Guclu yukselis trendi |
| ADX > 25 + DI asagi | — | -8 | Guclu dusus trendi |
| Bollinger alt bant | +10 | — | Fiyat alt bandin altinda |
| Bollinger ust bant | — | -10 | Fiyat ust bandin ustunde |
| Stochastic Bullish Cross | +8 | — | K, D'yi yukari kesti |
| CCI < -100 | +8 | — | CCI asiri satim |
| Hacim patlamasi + yukselis | +8 | — | Yuksek hacimle yukselis |
| RSI Bullish Divergence | +15 | — | Fiyat duser RSI yukselir |
| MACD Bullish Divergence | +12 | — | Guclu donus sinyali |
| OBV yukselis | +4 | — | Para girisi |
| Destek yakinligi (<%2) | +6 | — | Fiyat destek seviyesine yakin |

Toplam skor -100 ile +100 arasinda kesilir.

### Sinyal Esikleri

| Skor | Sinyal |
|---|---|
| >= +40 | Guclu Al |
| >= +10 | Al |
| >= 0 | Zayif Al |
| <= -40 | Guclu Sat |
| <= -10 | Sat |
| <= 0 | Zayif Sat |
| Diger | Bekle |

### Ek Filtreler

- **ADX < 20** olan hisseler filtrelenir (trend yok, sinyal uretilmez)
- **EMA 200** uzerindeki hisselere ek skor verilir (uzun vadeli trend onay)
- **Hacim onay** — Hacim 20 gunluk ortalamanin 1.5x ustundeyse ek skor

### Risk Yonetimi

Her sinyal icin 5 farkli yontemle stop-loss ve hedef hesaplanir:

1. **ATR bazli** — ATR x 2 stop, ATR x 3 hedef
2. **Destek/Direnc** — En yakin destek ve direnc seviyeleri
3. **Fibonacci** — 60 gunluk swing icindeki Fibonacci seviyeleri
4. **Yuzdelik** — Sabit %5 stop, %8 hedef
5. **Swing** — Yerel dip ve tepe noktalari

Bu 5 yontemin sonuclari karsilastirilir, en makul (%1-%10 arasi) stop secilir. Birden fazla yontem birbirine yakinsa guven "YUKSEK" olur.

## Proje Yapisi

```
bist_bot/
├── main.py              # Ana bot dongusu + CLI giris noktasi
├── config.py            # Tum yapilandirma ve sabitler
├── data_fetcher.py      # yfinance ile veri cekme + cache
├── indicators.py        # 15+ teknik gosterge hesaplamalari
├── strategy.py          # Skor bazli sinyal motoru
├── risk_manager.py      # Coklu yontem stop-loss/hedef hesabi
├── notifier.py          # Telegram bildirim sistemi
├── database.py          # SQLite: sinyaller, loglar, paper trade
├── backtest.py          # Gercekci backtest motoru (komisyon + kayma)
├── walk_forward.py      # Walk-forward parametre optimizasyonu
├── price_predictor.py   # GradientBoosting fiyat tahmini
├── streamlit_app.py     # Streamlit dashboard (ana arayuz)
├── streamlit_utils.py   # Streamlit yardimci fonksiyonlari
├── mobile_app.py        # Mobil optimize Streamlit arayuzu
├── dashboard.py         # Flask REST API + web dashboard
├── start_app.py         # Windows icin Streamlit baslatici
├── run_app.bat          # Windows batch baslatici
├── templates/           # Flask HTML sablonlari
├── models/              # Kaydedilmis ML modelleri (.pkl)
├── android_app/         # Kotlin/Jetpack Compose Android uygulamasi
├── requirements.txt     # Python bagimliliklari
├── .env.example         # Ortam degiskenleri sablonu
└── bist_signals.db      # SQLite veritabani (otomatik olusur)
```

## Yapilandirma

`config.py` dosyasindan ayarlari degistirebilirsiniz:

### Gosterge Parametreleri

| Parametre | Varsayilan | Aciklama |
|---|---|---|
| `RSI_PERIOD` | 14 | RSI hesaplama periyodu |
| `RSI_OVERSOLD` / `RSI_OVERBOUGHT` | 30 / 70 | RSI esik degerleri |
| `SMA_FAST` / `SMA_SLOW` | 5 / 20 | SMA hareketli ortalama |
| `EMA_FAST` / `EMA_SLOW` / `EMA_LONG` | 12 / 26 / 200 | EMA hareketli ortalama |
| `MACD_FAST` / `MACD_SLOW` / `MACD_SIGNAL` | 12 / 26 / 9 | MACD parametreleri |
| `BOLLINGER_PERIOD` / `BOLLINGER_STD` | 20 / 2 | Bollinger Bantlari |
| `ADX_THRESHOLD` | 20 | Minimum ADX (trend gucu) |
| `VOLUME_CONFIRM_MULTIPLIER` | 1.5 | Hacim onay carpani |

### Bot Ayarlari

| Parametre | Varsayilan | Aciklama |
|---|---|---|
| `SCAN_INTERVAL_MINUTES` | 15 | Tarama araligi (dakika) |
| `MARKET_OPEN_HOUR` | 10 | Borsa acilis saati |
| `MARKET_CLOSE_HOUR` | 18 | Borsa kapanis saati |
| `TELEGRAM_MIN_SCORE` | 70 | Telegram'a gonderilecek min skor |
| `PAPER_MODE` | False | Paper trading modu |
| `SECTOR_LIMIT` | 2 | Ayni sektorden max sinyal |

### Backtest Ayarlari

| Parametre | Varsayilan | Aciklama |
|---|---|---|
| `COMMISSION_BUY` / `COMMISSION_SELL` | 0.02% | Alim/satim komisyonu |
| `BSMV` | 0.05% | BSMV vergisi |
| `SLIPPAGE` | 0.1% | Tahmini kayma |
| `WALKFORWARD_TRAIN_DAYS` | 180 | Walk-forward egitim suresi |
| `WALKFORWARD_TEST_DAYS` | 30 | Walk-forward test suresi |

## Ortam Degiskenleri

`.env.example` dosyasini `.env` olarak kopyalayip doldurun:

```env
TELEGRAM_BOT_TOKEN=buraya_bot_token_yaz
TELEGRAM_CHAT_ID=buraya_chat_id_yaz
```

- **TELEGRAM_BOT_TOKEN**: [@BotFather](https://t.me/BotFather)'dan alinir
- **TELEGRAM_CHAT_ID**: [@userinfobot](https://t.me/userinfobot)'dan alinir

Telegram ayarlanmazsa bot calismaya devam eder, sadece bildirim gondermez.

## Ornek Backtest Ciktisi

```
═══════════════════════════════════════════════════════
📊 BACKTEST SONUCU: THYAO.IS
═══════════════════════════════════════════════════════
  Periyot         : 15.04.2025 → 12.04.2026
  Baslangic       : ₺8,500.00
  Bitis           : ₺9,234.50
  Toplam Getiri   : %8.64
  ─────────────────────────────────
  Toplam Islem    : 12
  Kazanan         : 8
  Kaybeden        : 4
  Kazanma Orani   : %66.7
  ─────────────────────────────────
  Ort. Kar        : %3.42
  Ort. Zarar      : %-1.87
  Max Drawdown    : %-4.21
  Sharpe Ratio    : 1.24
═══════════════════════════════════════════════════════
```

*Not: Yukaridaki degerler ornektir. Gercek sonuclar piyasa kosullarina gore degisir.*

## Ornek Sinyal Ciktisi

```
==================================================
📊 ASELSAN (ASELS.IS)
==================================================
  Sinyal  : 💰 GUCLU AL
  Skor    : +52.0/100
  Fiyat   : ₺68.45
  Guven   : YUKSEK
  Stop-Loss: ₺64.20
  Hedef   : ₺74.80
  Nedenler:
    RSI dusuk (28.3) → Asiri satim
    MACD Bullish Crossover 📈
    SMA Golden Cross ✨ → Yukselis sinyali
    Hacim onay (2.1x ort)
    Guclu yukselis trendi (ADX:32, +DI>18)
    R/R: 1:1.5 | Stop: ATR | Hedef: Direnc
  Zaman   : 12.04.2026 14:30
==================================================
```

*Not: Yukaridaki degerler ornektir.*

## Teknolojiler

| Katman | Teknoloji |
|---|---|
| Veri | yfinance, pandas, numpy |
| ML | scikit-learn (GradientBoosting) |
| Web UI | Streamlit, Flask |
| Grafik | Plotly |
| Bildirim | Telegram Bot API |
| Veritabani | SQLite |
| Mobil | Kotlin, Jetpack Compose (Android) |

## Ekran Goruntuleri

> Streamlit ve Flask arayuzlerinin ekran goruntuleri icin `screenshots/` klasorune bakin.
> Ornek goruntuler henuz eklenmedi; katkida bulunmak isterseniz PR gonderebilirsiniz.

<!-- Ekran goruntuleri eklendiginde asagidaki satirlarin yorumunu kaldir:
![Streamlit Dashboard](screenshots/streamlit_dashboard.png)
![Sinyal Detay](screenshots/sinyal_detay.png)
![Backtest Sonucu](screenshots/backtest_sonuc.png)
-->

## Uyarilar

- Bu yazilim **yatirim tavsiyesi degildir**. Tum kararlariniz size aittir.
- Gecmis performans gelecegi garanti etmez.
- Paper trading modunu kullanarak once stratejiyi test edin.
- Bot, yfinance uzerinden veri ceker; API limitlerine dikkat edin.

## Gelistirme Notlari

- Repoyu temiz tutmak icin gecici build, IDE ve cache dosyalari versiyon kontrolune dahil edilmemelidir.
- Uygulamayi gelistirmeden once `.env.example` dosyasini kopyalayip kendi `.env` dosyanizi olusturun.

## Lisans

MIT License — Detaylar icin [LICENSE](LICENSE) dosyasina bakin.
