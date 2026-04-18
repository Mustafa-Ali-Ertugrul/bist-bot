# BIST Bot — Borsa İstanbul Sinyal Botu

BIST hisselerini teknik indikatörlerle tarayan, sinyal üreten, Telegram'a bildiren ve paper trade kaydeden otonom bir bot.

## Özellikler

- RSI, MACD, Bollinger, SMA, EMA, ADX, Stochastic, CCI, OBV, Divergence
- 7 kademeli sinyal: GÜÇLÜ AL → ZAYIF AL → BEKLE → ZAYIF SAT → GÜÇLÜ SAT
- Pazar saati farkındalığı (açılış, kapanış, yarım gün, hafta sonu)
- Telegram bildirimleri ve sinyal değişim uyarıları
- Paper trade modu
- Backtest desteği
- Ruff lint + pytest CI

## Mimari

```mermaid
#mermaid-r44t{font-family:inherit;font-size:16px;fill:#E5E5E5;}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#mermaid-r44t .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#mermaid-r44t .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#mermaid-r44t .error-icon{fill:#CC785C;}#mermaid-r44t .error-text{fill:#3387a3;stroke:#3387a3;}#mermaid-r44t .edge-thickness-normal{stroke-width:1px;}#mermaid-r44t .edge-thickness-thick{stroke-width:3.5px;}#mermaid-r44t .edge-pattern-solid{stroke-dasharray:0;}#mermaid-r44t .edge-thickness-invisible{stroke-width:0;fill:none;}#mermaid-r44t .edge-pattern-dashed{stroke-dasharray:3;}#mermaid-r44t .edge-pattern-dotted{stroke-dasharray:2;}#mermaid-r44t .marker{fill:#A1A1A1;stroke:#A1A1A1;}#mermaid-r44t .marker.cross{stroke:#A1A1A1;}#mermaid-r44t svg{font-family:inherit;font-size:16px;}#mermaid-r44t p{margin:0;}#mermaid-r44t .label{font-family:inherit;color:#E5E5E5;}#mermaid-r44t .cluster-label text{fill:#3387a3;}#mermaid-r44t .cluster-label span{color:#3387a3;}#mermaid-r44t .cluster-label span p{background-color:transparent;}#mermaid-r44t .label text,#mermaid-r44t span{fill:#E5E5E5;color:#E5E5E5;}#mermaid-r44t .node rect,#mermaid-r44t .node circle,#mermaid-r44t .node ellipse,#mermaid-r44t .node polygon,#mermaid-r44t .node path{fill:transparent;stroke:#A1A1A1;stroke-width:1px;}#mermaid-r44t .rough-node .label text,#mermaid-r44t .node .label text,#mermaid-r44t .image-shape .label,#mermaid-r44t .icon-shape .label{text-anchor:middle;}#mermaid-r44t .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#mermaid-r44t .rough-node .label,#mermaid-r44t .node .label,#mermaid-r44t .image-shape .label,#mermaid-r44t .icon-shape .label{text-align:center;}#mermaid-r44t .node.clickable{cursor:pointer;}#mermaid-r44t .root .anchor path{fill:#A1A1A1!important;stroke-width:0;stroke:#A1A1A1;}#mermaid-r44t .arrowheadPath{fill:#0b0b0b;}#mermaid-r44t .edgePath .path{stroke:#A1A1A1;stroke-width:2.0px;}#mermaid-r44t .flowchart-link{stroke:#A1A1A1;fill:none;}#mermaid-r44t .edgeLabel{background-color:transparent;text-align:center;}#mermaid-r44t .edgeLabel p{background-color:transparent;}#mermaid-r44t .edgeLabel rect{opacity:0.5;background-color:transparent;fill:transparent;}#mermaid-r44t .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#mermaid-r44t .cluster rect{fill:#CC785C;stroke:hsl(15, 12.3364485981%, 48.0392156863%);stroke-width:1px;}#mermaid-r44t .cluster text{fill:#3387a3;}#mermaid-r44t .cluster span{color:#3387a3;}#mermaid-r44t div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:inherit;font-size:12px;background:#CC785C;border:1px solid hsl(15, 12.3364485981%, 48.0392156863%);border-radius:2px;pointer-events:none;z-index:100;}#mermaid-r44t .flowchartTitleText{text-anchor:middle;font-size:18px;fill:#E5E5E5;}#mermaid-r44t rect.text{fill:none;stroke-width:0;}#mermaid-r44t .icon-shape,#mermaid-r44t .image-shape{background-color:transparent;text-align:center;}#mermaid-r44t .icon-shape p,#mermaid-r44t .image-shape p{background-color:transparent;padding:2px;}#mermaid-r44t .icon-shape rect,#mermaid-r44t .image-shape rect{opacity:0.5;background-color:transparent;fill:transparent;}#mermaid-r44t .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#mermaid-r44t .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#mermaid-r44t :root{--mermaid-font-family:inherit;}main.py - Wiring & CLIScanServiceMarketSchedulerBacktestRunnerBISTDataFetcherStrategyEngineTelegramNotifierSignalDatabaseTechnicalIndicatorsRiskManager
```

## Proje Yapısı

```text
bist_bot/
├── main.py              # CLI giriş noktası, bağımlılık kurulumu
├── scanner.py           # ScanService — tarama, sinyal değişim, paper trade
├── scheduler.py         # MarketScheduler — pazar saati döngüsü
├── backtest_runner.py   # Backtest akışı
├── strategy.py          # StrategyEngine — 4 modüler skor metodu
├── indicators.py        # Teknik indikatör hesaplamaları
├── risk_manager.py      # Stop-loss, hedef fiyat, pozisyon büyüklüğü
├── data_fetcher.py      # yfinance veri çekme ve önbellekleme
├── notifier.py          # Telegram bildirimleri
├── database.py          # SQLite sinyal ve paper trade kaydı
├── backtest.py          # Backtester sınıfı
├── dashboard.py         # Flask web paneli
├── streamlit_app.py     # Streamlit arayüzü
├── mobile_app.py        # Mobil Streamlit arayüzü
├── config.py            # Tüm yapılandırma sabitleri
├── tests/               # pytest test paketi
└── requirements.txt
```

## Kurulum

```bash
pip install -r requirements.txt
```

`.env` dosyası oluştur:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## Kullanım

```bash
python main.py              # Bot + dashboard
python main.py --once       # Tek tarama
python main.py --backtest   # Backtest
python main.py --dashboard  # Sadece dashboard
streamlit run streamlit_app.py
```

## Test & Lint

```bash
pytest tests/ -v
ruff check . --isolated
```

## Lisans

MIT
