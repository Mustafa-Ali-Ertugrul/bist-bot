# H10 — MIN_LIQUIDITY_VALUE_TL default-0 bypass audit

## ADIM 0 — Sonuç: **HAYIR**, walk-forward filtreyi TETİKLEMİYOR

### Bulgular

1. `apply_probability_sizing(...)` (`risk/sizing.py:64`) — sadece `risk/manager.py:275` içinden çağrılıyor.
2. `RiskManager(...)` walk-forward yolunda **HİÇ** instantiate edilmiyor:
   - `scripts/run_walk_forward_bist30.py` imports: indicators, scoring, regime, params, `WalkForwardValidator`. Risk/sizing **yok**.
   - `scripts/run_wf_cost_stress.py` imports: aynı — risk/sizing **yok**.
   - `scripts/run_walk_forward_conservative.py` imports: aynı — risk/sizing **yok**.
   - `src/bist_bot/validation/walk_forward.py` imports: `Backtester` (validasyon/backtest) — risk/sizing yok.
3. `src/bist_bot/backtest/engine.py` risk paketinden sadece **`calculate_kelly_fraction`** import eder;
   `apply_probability_sizing` veya `RiskManager` **import edilmez**.
4. RiskManager + apply_probability_sizing tek bir script'te geçiyor: `scripts/measure_score_impact.py` (ölçüm amaçlı, walk-forward **değil**).

### Sonuç

Walk-forward/backtest path, **`MIN_LIQUIDITY_VALUE_TL` filtresi çağırmadan** işlem üretiyor.
Bu yüzden `MIN_LIQUIDITY_VALUE_TL` default'unda yapılacak değişiklik **walk-forward metric'lerini etkilemez** (robust set, stress, overfit aynı kalır).

### Bu durumda (H1/H3 dersi)

- Backtest'i risk yoluna bağlamak **ayrı bir iş** (stop-metod parity backlog'unda) — şimdi yapma.
- Fix yine de canlı için mandatory: live trader SUBMIT etmeden önce risk manager'dan geçiyor, bu yüzden gerçek akışta fiilen likidite filtresi uygulanacak.
- Walk-forward beklentisi: **robust set değişmez, stress OOS değişmez, overfitting değişmez — sadece canlı güvenlik artar**. Dürüst not: WF bu fix'i **kör** ölçüyor.

## ADIM 1 — Fix (canlı için, scoring'e dokunmadan)

### Değişiklik

- `src/bist_bot/config/subsettings.py:233`
  - `MIN_LIQUIDITY_VALUE_TL: float = _get_float_env("MIN_LIQUIDITY_VALUE_TL", 0.0)`
  - **→** `MIN_LIQUIDITY_VALUE_TL: float = _get_float_env("MIN_LIQUIDITY_VALUE_TL", 5_000_000.0)`
  - 5M TL default — BIST için makul günlük ortalama hacim eşiği (SASA taban ~300M TL ADV dolaylarında; KONTR/HEKTS sığ).
  - Env var (`MIN_LIQUIDITY_VALUE_TL`) override olarak kullanılabilir, dokunulmadı.

### Etki

- `RiskManager.__init__` `self.min_liquidity_value_tl` field'ı 5M ile oluşur (`risk/manager.py:79`).
- `apply_probability_sizing` zaten doğru yere bağlı: `min_liquidity_value=self.min_liquidity_value_tl`
  (`risk/manager.py:284`) — filtre canlı runtime'da tetiklenir.
- `risk/profile.py`'deki conservative profile bu setting'i ayrı ele almıyor; `min_liquidity_value_tl`
  global settings'ten okunduğu için profilde de aynı eşik uygulanır (profil-bağımsız risk filtresi).
- Skor formülüne, H1/H3/H5/H8 bloklarına dokunulmadı.

### Conservative profile not'u

`risk/profile.py` `RiskProfile` pydantic modeli ayrı bir liquidity field içermez; tüm profiller
global `MIN_LIQUIDITY_VALUE_TL`'yi okur. Bu istenen davranış (risk filtresi profilde bağımsız olmamalı).

## ADIM 2 — Walk-forward SKIP (ADIM 0 HAYIR olduğu için)

Walk-forward bu fix'i kör ölçüyor. **Koşmaya gerek yok.** Eğer yine de baseline vs fix farkı
görmek isterseniz (sadece bilgi amaçlı, fix'e karar verdirmez):

- `python scripts/run_walk_forward_bist30.py --counter-trend-multiplier 0.0`
- `python scripts/run_wf_cost_stress.py --counter-trend-multiplier 0.0`
- Beklenti: baseline (MIN_LIQUIDITY=0) ile **byte-for-byte aynı** CSV çıktısı, çünkü backtest
  risk yolunu çağırmıyor.
- Karar kuralı uygulanmaz (no-effect kontrol). Bu durumda sweep yok, geri-al yok.

## Test doğrulaması

### Yeni testler (`tests/test_ml_position_sizing.py`)

- `test_min_liquidity_default_threshold_is_5m_tl` — env yokken dataclass field default 5M.
- `test_min_liquidity_blocks_when_below_5m_tl` — `mult=0.5` (~600k TL) → blocked.
- `test_min_liquidity_passes_when_above_5m_tl` — `mult=5.0` (~6M TL) → pos_size > 0.

### Mevcut testler dolaylı olarak etkilendi (env-override'a açık hale getirildi)

- `test_probability_sizing_applies_fractional_kelly_cap` — bypass için `min_liquidity_value_tl=0.0` eklendi.
- `test_daily_loss_under_cap_allows_trading` — same.

### Çalıştırma sonucu

```
tests/test_ml_position_sizing.py                       7 passed
tests/test_risk_manager_integration.py                12 passed
tests/test_risk_manager.py + ... (sizing/risk bütünü) 75 passed
ruff check (subsettings + tests)                      All clean
```

## Notlar ve follow-up

1. **`results/score_engine_audit.md` H10 maddesi** kapanır — canlı filtre aktif.
2. **Ölçülebilirlik gerçek çözüm**: backtest engine'in `RiskManager.apply_probability_sizing` çağırması.
   Backlog'a alındı (stop-metod parity maddesiyle birlikte düşünülebilir; şimdi yapma, scope kontrol).
3. Prod `.env`'de `MIN_LIQUIDITY_VALUE_TL` yok → default 5M canlıda uygulanır.
   Dev `.env`'de eskiden `MIN_LIQUIDITY_VALUE_TL=0.0` vardı (template/template ayarı).
   Bunu override olarak bıraktık; dev kasıtlı olarak 0 istiyorsa override eder — gerekmezse
   dev ortamı default 5M'i alır (`.env`'den kaldırılınca).
