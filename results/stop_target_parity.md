# H8: Stop/Target Parity Raporu

## ADIM 0 — Stop/Target Kaynak Analizi

### Canlı yol (RiskManager)
- `src/bist_bot/risk/manager.py:210` → `self._determine_final_levels(price, levels)`
- `src/bist_bot/risk/manager.py:235-236` → `stop_helpers.determine_final_levels(price, levels)`
- `src/bist_bot/risk/stops.py:119` → `determine_final_levels(price, levels)`

### Backtest yol (Backtester)
- `src/bist_bot/backtest/engine.py:178-186` → **determine_final_levels'ı çağırmaz.**
- Backtest kendi vektörel stop/target mantığını kullanır:
  - `calculated_stop = df["stop_loss_atr"].fillna(df["close"] * 0.95)`
  - `target_price = close + risk_per_share * target_rr`
- Bu, **ayrık (separate)** bir yol. Backtest, canlı `determine_final_levels`'dan bağımsızdır.

### Karar
- Backtest vektörel stop simülasyonu, `determine_final_levels`'ın metod-seçimini (ATR/Destek/Fibonacci/Swing/Yüzdelik) yapmaz.
- H8 tick rounding, **her iki yola da** uygulanmalıdır (BIST fiyat adımı bir piyasa kuralıdır, strateji değildir).
- Backtest, ham (un-rounded) stop/target ile simüle etmişti. Bu **bilinçli bir farktı**, şimdi tick rounding ile giderildi.
- `determine_final_levels` H8 güncellemeleri (tick rounding, daily limit, ATR sanity) **canlı yol için** geçerlidir.
- Backtest, ayrıca kendi tick rounding'ini uygular (engine.py:187-188).

## Durum: AYRIK (canlı-only tick + backtest tick)
Her iki yol da ayrı ayrı tick rounding uygular. Canlı yol ek olarak daily limit + ATR sanity içerir.
