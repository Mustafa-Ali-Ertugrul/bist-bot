# Pozisyon Yaşam Döngüsü Sözleşmesi (Paper Yolu)

> Faz 3 P3 — uzman raporunun "pozisyon yönetimi netliği: EKSİK" maddesinin cevap tablosu.
> Her kuralın kod referansı verilmiştir; davranış değişirse bu doküman da güncellenmelidir.

## Kapanış Kuralları (öncelik sırasıyla)

| # | Olay | Kapanış Nedeni | Koşul | Kod |
|---|------|----------------|-------|-----|
| 1 | Ters sinyal | `OPPOSITE_SIGNAL` | Açık pozisyon yönünün tersine sinyal geldi **ve** `\|skor\| ≥ 15` | `paper_trade_service.py` → `update_open_trades` (opposite_signal bloğu) |
| 2 | Orijinal stop | `STOP_HIT` | Long: `fiyat ≤ stop_loss` · Short: `fiyat ≥ stop_loss` | `update_open_trades` (stop_hit kontrolü) |
| 3 | Trailing stop | `TRAIL_STOP_HIT` | `TRAILING_STOP_ENABLED=True` iken fiyat, extreme'ten `TRAILING_STOP_PCT` geri çekildi (aşağıda) | `update_open_trades` (trail_hit kontrolü) |
| 4 | Hedef | `TARGET_HIT` | Long: `fiyat ≥ target_price` · Short: `fiyat ≤ target_price` | `update_open_trades` (target_hit kontrolü) |
| 5 | Seans sonu | `EOD_CLOSE` | TR saati ≥ `bist_close_time(tarih)` (tam gün 17:30, yarım gün 12:30; tatil/hafta sonu tetiklemez) | `paper_trade_service._is_eod` → `market_calendar.bist_close_time` |

Aynı taramada birden fazla koşul geçerliyse **yukarıdaki sıra** kazanır
(ör. stop ve hedef aynı barda → `STOP_HIT`; stop ve EOD aynı taramada → `STOP_HIT`).
Bu, backtest ölçüm sözleşmesiyle aynıdır ("stop wins", konservatif).

## Trailing Stop Detayı (P2)

- **Tek kaynak:** `AgentSettings.TRAILING_STOP_ENABLED` (default **False**) + `TRAILING_STOP_PCT` (default %2.0). Yeni ayar eklenmedi.
- **Mekanizma:** Her taramada extreme güncellenir — long için giriş sonrası **en yüksek** fiyat (`max`), short için **en düşük** (`min`). Extreme giriş fiyatından başlar.
  - Long trail: `extreme × (1 − PCT/100)` → stop yalnızca **yukarı** sıkışır.
  - Short trail: `extreme × (1 + PCT/100)` → stop yalnızca **aşağı** sıkışır.
- **Kalıcılık:** In-memory (`_trail_extremes` dict). Restart'ta watermark kaybolur → **orijinal stop geçerli olur** (güvenli yönde bozulma; trail yalnızca daralttığı için en kötü durum eski davranıştır). DB kolonu/migration bu fazda gerekmez.
- **Sınıflandırma:** Trail, orijinal stopu geçmişse (daha darsa) ihlalde `TRAIL_STOP_HIT`; orijinal stop hâlâ daha darsa ihlal `STOP_HIT` olarak raporlanır.

## EOD Disiplini Detayı (P1)

- Sözleşme `SignalOutcomeTracker._is_eod` ile **birebir aynıdır**: `market_calendar.bist_close_time(d)` tek kaynaktır; yarım gün tarihleri `_HALF_DAY_DATES` kümesinden gelir (şu an boş → tüm günler tam seans 17:30). Bilinen yarım günler eklendiğinde paper ve tracker otomatik hizalanır.
- 16:30'da açılan pozisyon da aynı seansın kapanışında `EOD_CLOSE` olur; kısa tutma süresi `holding_min` kolonunda görünür. Bu bilinçli bir karardır: intraday stratejide gecike taşınan pozisyon ayrı bir strateji değildir.

### P1.1 — Post-Close Hook (üretim tetikleyicisi)

`_is_eod` yalnızca bir tarama çalıştığında değerlendirilir; scheduler normalde kapanışta
ertesi seansa uyuduğu için üretimde EOD asla tetiklenmezdi. Bu yüzden:

- `ScanService.close_positions_at_eod(now)` — sessiz pas: günlük kapanış fiyatlarını
  fetch eder, paper pozisyonları (`update_open_trades(signals=None)`) ve tracked
  outcome'ları (`process_scan([], market_data)`) gerçek fiyatla kapatır. Sinyal
  kaydetmez, bildirim göndermez.
- `MarketScheduler._pending_eod_close / _run_eod_close` — **tarih anahtarlı, günde 1**
  tetik: `bist_close_time + EOD_CLOSE_DELAY_MINUTES` (default 2 dk → ~17:32). Hem ana
  döngüde hem iki bekleme döngüsünde kontrol edilir; tatil/hafta sonu tetiklenmez,
  ertesi sabah double-run olmaz. Hata durumunda bile "yapıldı" işaretlenir (spam önleme).

## Skor Decay Uyarısı (F3.4, rapor-only)

- Günlük rapor §7'de açık pozisyonun **giriş skoru** güncel `buy_threshold`'un altına düştüyse ve TR saati ≥ 15:30 ise satır `⚠️ skor eşiğin altında (T+1 riski)` uyarısı alır.
- Telegram'a gönderilmez (spam önleme); yalnızca `results/daily_report_*.md` içinde görünür.

## Kapsam Dışı (bilinçli)

KAP/haber entegrasyonu · sentiment/social · spread ve kademe derinliği filtresi (veri katmanında yok — ayrı veri kaynağı projesi) · VIOP · backtest yolu değişikliği · agent trailing default'unun açılması.
