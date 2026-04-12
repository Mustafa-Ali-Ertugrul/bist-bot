# BIST Bot - BIST Hisse Senedi Sinyal Botu

Borsa İstanbul (BIST) hisse senetleri için teknik analiz ve alım/satım sinyalleri üreten otomatik bir bot.

## Özellikler

- Teknik indikatörler: RSI, MACD, Bollinger Bantları, SMA, EMA
- Çoklu hisse desteği (60+ hisse)
- Telegram bildirimleri
- Streamlit dashboard
- Flask web arayüzü
- Backtest desteği
- Risk yönetimi

## Kurulum

### 1. Python Kurulumu

Python 3.10+ gereklidir:

```bash
python --version
```

### 2. Bağımlılıkları Yükleyin

```bash
pip install -r requirements.txt
```

### 3. Çevre Değişkenleri

`.env` dosyası oluşturun:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Telegram bot token almak için: [@BotFather](https://t.me/BotFather)
Chat ID almak için: [@userinfobot](https://t.me/userinfobot)

## Kullanım

### Terminal/Uygulama

```bash
python main.py
```

### Streamlit Dashboard

```bash
streamlit run streamlit_app.py
```

### Flask Web Arayüzü

```bash
python dashboard.py
```

### Mobil Uygulama

```bash
streamlit run mobile_app.py
```

## Yapılandırma

`config.py` dosyasından ayarları değiştirebilirsiniz:

- `WATCHLIST`: Takip edilecek hisse senetleri
- `RSI_PERIOD`, `RSI_OVERSOLD`, `RSI_OVERBOUGHT`: RSI ayarları
- `SMA_FAST`, `SMA_SLOW`: Basit hareketli ortalama
- `EMA_FAST`, `EMA_SLOW`: Üstel hareketli ortalama
- `MACD_*`: MACD parametreleri
- `BOLLINGER_*`: Bollinger Bantları ayarları
- `SCAN_INTERVAL_MINUTES`: Tarama aralığı (dakika)
- `MARKET_OPEN_HOUR`, `MARKET_CLOSE_HOUR`: Pazar saatleri

## Sinyal Türleri

- **AL**: RSI < 30, MACD cross向上, fiyat alt Bollinger bandı
- **SAT**: RSI > 70, MACD cross向下, fiyat üst Bollinger bandı
- **NÖTR**: Sinyal yok

## Proje Yapısı

```
bist_bot/
├── main.py           # Ana bot
├── config.py        # Yapılandırma
├── data_fetcher.py  # Veri çekme
├── indicators.py    # Teknik indikatörler
├── strategy.py     # Strateji motoru
├── notifier.py     # Telegram bildirimi
├── database.py    # SQLite veritabanı
├── backtest.py    # Backtest
├── risk_manager.py # Risk yönetimi
├── streamlit_app.py # Streamlit UI
├── dashboard.py   # Flask Dashboard
├── mobile_app.py  # Mobil UI
├── requirements.txt
└── README.md
```

## Teknolojiler

- **yfinance**: Hisse verisi
- **pandas/numpy**: Veri analizi
- **streamlit**: Web UI
- **flask**: Web framework
- **plotly**: Grafikler
- **sqlite3**: Yerel veritabanı

## Lisans

MIT