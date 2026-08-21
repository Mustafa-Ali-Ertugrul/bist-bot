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

## Z2: Faz 2 Yakınsama — Canlı Yol Volatilite-Adaptif

- Canlı `determine_final_levels` artık **Yüzdelik fallback'i volatilite-adaptif**:
  - `Yüzdelik` seçildiyse ve `ATR` geçerliyse → `target = price + max(ATR_TARGET_MULT*ATR, FALLBACK_TARGET_RR*risk)` clamp `[price*(1+ATR_TARGET_FLOOR_PCT), price*1.10]`
  - `ATR_TARGET_MULT=1.5` (default), `FALLBACK_TARGET_RR=2.0` → backtest'in `close + risk*2.0` sözleşmesiyle yakınsar
  - +8% kümelemesi kalkar: sığ vol hisselerde ATR hedefi + fallback RR tabanlı hedef (risk*2) ile değişir
- **Stop tabanı:** `MIN_STOP_LOSS_PCT=1.5` → `final_stop = min(final_stop, price*(1-1.5%))` (limit clamp sonrası, tick öncesi); 1.1% tetik stopları genişler
- **Backtest yolu ayrık kalır** (repo sözleşmesi): backtest kendi vektörel `close + risk*2.0` mantığını korur; Z2 değişikliği backtest'i etkilemez, walk-forward delta=0 beklenir
