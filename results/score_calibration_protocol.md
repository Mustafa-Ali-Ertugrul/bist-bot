# Skor Kalibrasyon Kararlaştırma Protokolü (Ön-Commitli)

> Faz 3 P5 — "hedef/stop gerçekçiliği test edilmeli" maddesinin veri-biriktir-sonra-karar ver protokolü.
> **Bu doküman kuralları önceden sabitler** (pre-commit): veri geldiğinde sonradan
> rasyonelleştirme yapılamaz; kurala uymayan sonuç "inceleme adayı"dır, otomatik değişiklik değildir.

## Tetikleyici

İlk koşul gerçekleştiğinde protokol **zorunlu** olarak işletilir:

- `results/signal_outcomes.csv` içinde **≥ 30 kapanmış outcome**, **veya**
- tracker devreden beri **10 işlem günü** geçti (hangisi önce olursa).

## Koşu

```bash
python main.py --score-correlation
# -> results/score_correlation.md
```

Araç `reports/score_correlation.py`: skor bucket'ları (25-30 / 30-35 / 35-40 / 40+)
başına win-rate, ort. net PnL, ort. MFE/MAE, ort. tutma süresi + Pearson
skor↔net-PnL ve skor↔MFE korelasyonu üretir (`is_win = net_pnl > 0 veya TARGET_HIT`).

## Ön-Commitli Karar Kuralları

| Sonuç | Karar |
|-------|-------|
| Bucket win-rate'leri **monoton artıyor** (25-30 < 30-35 < 35-40 < 40+) **ve** toplam net win-rate ≥ %50 **ve** skor↔PnL r > 0.2 | Eşikler **korunur** — skor bilgi taşıyor, kalibrasyon başarılı sayılır. Sonuç `results/score_calibration_YYYY-MM-DD.md`'ye yazılır. |
| Herhangi bir bucket: net win-rate **< %40** ve bucketta **n ≥ 10** | O bucket yönünde **eşik yükseltme adayı** doğar. Canlı eşik hemen değiştirilmez; aday önce backtest harness'te (walk-forward) doğrulanır, pozitifse ayrı commit ile uygulanır. |
| Korelasyon **düz veya negatif** (r ≤ 0) **ve** n ≥ 30 | Skor modeli incelemesi açılır → **Faz 4 adayı** (ayrı initiative; bu protokol kapsamında eşik oynanmaz). |
| n < 30 | Karar verilmez — "yetersiz örnek" kaydı düşülür, tetik yeniden beklenir. |

## Teslim Formatı

Her koşudan sonra `results/score_calibration_YYYY-MM-DD.md`:

1. Koşu tarihi + tetikleyici (30 outcome mu 10 gün mü)
2. `score_correlation.md` bucket tablosunun kopyası
3. Hangi kuralın tetiklendiği (yukarıdaki tablodan satır referansı)
4. Karar + gerekçe (eşik korundu / yükseltme adayı / Faz 4 adayı)
5. Varsa config değişikliğinin commit SHA'sı

## Bilinen Sınırlar (bu fazda düzeltilmedi, bilinçli)

- Bucket sınırları (25/30/35/40) `buy_threshold=25` (conservative) varsayar; default profil (20) kullanılırsa 20-25 bandı ölçülmez. Protokol ilk koşusunda profil notu ekler.
- Saat bucket'ları UTC proxy'sidir; TR seans hizası Faz 4 adayıdır.
- Win tanımı `net_pnl > 0 veya TARGET_HIT` — maliyet sonrası pozitiflik ile hedef vuruşunu tek bayrakta birleştirir.
