# Deney F — PV Confirmation Gate Raporu (suçlu düzeltmesi #1)

**Tarih:** 2026-08-28 · **Git SHA:** `59c41f4d7e866e7a4c9fee106b0d58b6cdd3085f` · **Kanıt zinciri:** Deney E Faz 0+1 → bu düzeltme

## Kanıt → düzeltme eşlemesi

Deney E Faz 1, 508 sinyalin **%30'unun (n=153)** `price_volume_direction != BULLISH_CONFIRMATION` günlerde üretildiğini ve bu alt-kümenin **mean −%1.51 / up %39.2** ile zarar kovası olduğunu gösterdi (pv_bull=1 kümesi: +%1.03 / %55.8). score_volume dışındaki 3 bileşenin sinyal-günü IC'si ≈ 0 olduğundan, birleşik skor bu zehirli alt-kümeyi eşikten geçiriyordu.

**Düzeltme (opt-in, varsayılan kapalı):** `StrategyParams.pv_confirmation_required=False` yeni alan; açıkken `calculate_score_and_reasons` içinde **son giriş filtresi** olarak long aday (score ≥ buy_threshold) pv ≠ BULLISH_CONFIRMATION ise reddedilir. Varsayılan = mevcut davranış (off == observe invariant'ı testlerle kilitli).

## Uygulama invariantları (PASS)

- Varsayılan kapalı: mevcut tüm test paketi davranışı değişmeden geçiyor (**1404 passed, 2 skipped**)
- Parity testleri (engine ↔ backtest) yeşil
- Per-signal A/B: **eklenen sinyal = 0**, 355 ortak anahtarda getiri/exit/score **uyumsuzluk = 0**

## Per-signal A/B (`results/prediction_signals_expF_pv_gate.csv` vs baseline)

| Küme | n | WR | mean net | Toplam net PnL |
|---|---|---|---|---|
| Baseline | 508 | %47.4 | −%0.18 | **−88,784 TL** |
| **pv-gate** | **355** | **%52.7** | **+%0.46** | **+162,925 TL** |
| Engellenen (pv_bull=0) | 153 | %35.3 | −%1.65 | **−251,709 TL** |

Kapı, kanıtın işaret ettiği zarar kovasını tam olarak kesti: engellenen 153 sinyal −251.7k TL taşıyordu; kalan 355 sinyal +162.9k TL.

## Walk-forward A/B (`results/walk_forward_expF_pv_gate.csv` vs `walk_forward_expD_macro_observe.csv`)

| Ölçü | Baseline | pv-gate |
|---|---|---|
| Pozitif OOS payı | 19/30 | 18/30 |
| Mean OOS | +1.19% | +1.27% |
| Median OOS | +1.01% | +1.28% |
| Mean max DD | −7.02% | **−6.30%** |
| OOS trades | 266 | 224 (%84) |
| Overfit payı | 14/30 | 16/30 |

WF portföy seviyesinde: mean/median/DD hafif iyileşti, pozitif pay 19→18, overfit 14→16 (kötüleşme — izlenecek). Per-signal iyileşmesi portföy seviyesine kısmen yansıyor: aynı gün çoklu sinyallerde kapı bazen tek pozisyonu değil sırayı değiştiriyor.

## Karar

**Düzeltme kanıtlandı** ama Deney D disiplini gereği **varsayılan profil değiştirilmedi** — kapı opt-in flag olarak duruyor (`--pv-confirmation-required`). Varsayılan aktivasyon ayrı kullanıcı onayı gerektirir; karar öncesi Faz 2-4 ölçümleri (özellikle sideways çarpanı ve çıkış yüzeyi) tamamlanmalı.

## Dosyalar

- `src/bist_bot/strategy/params.py`: `pv_confirmation_required` alanı
- `src/bist_bot/strategy/engine_filters.py`: gate (son giriş filtresi, reject_logger entegre)
- `scripts/evaluate_july_2026_predictions.py`, `scripts/run_walk_forward_bist30.py`: `--pv-confirmation-required`
- `tests/test_pv_confirmation_gate.py`: 6 test
- Sonuçlar: `results/prediction_signals_expF_pv_gate.csv`, `results/walk_forward_expF_pv_gate.csv`
