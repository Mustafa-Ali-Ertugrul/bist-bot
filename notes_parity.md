# Backtest Parity Measurement (Pre-Refactor)

## Run details
- Command: `python scripts/measure_backtest_parity.py --limit 5`
- Tickers: AKBNK.IS, ARCLK.IS, ASELS.IS, ASTOR.IS, BIMAS.IS
- Period: 3y
- Params: StrategyParams.conservative(), counter_trend_multiplier=0.0

## Results
- Total rows compared: 3453
- Rows with |delta| > 1 (live vs vec): 3334 (96.6%)
- Max |delta| (live vs vec): 68.60
- Rows with |delta| > 1 (basic vs vec): 3272 (94.8%)
- Max |delta| (basic vs vec): 68.60

## Verdict
- **BASIC (H1/H3-free) scoring ALSO differs -> iki beyin zaten farkliydi (skor temelde ayrismali).**
- The two scoring engines disagree even on raw component scores, not just H1/H3.

## Key Differences Found
1. **EMA trend logic**: Vectorized gives `score_ema_cross` (10.0) unconditionally when price > EMA. `score_trend` only gives it when ADX >= `params.adx_threshold`.
2. **ADX threshold**: Vectorized uses hardcoded 25. `score_trend` uses `params.adx_threshold` (20 for conservative).
3. **ADX scoring**: Vectorized uses `score_adx_strong`/`score_adx_weak` based on `adx > 25`. `score_trend` uses `params.adx_threshold` and gives `score_adx_strong` when `adx > 25` (hardcoded in score_trend too, but with different conditions).

## Sample Row (AKBNK.IS 2023-10-20)
- vec_score: 24.1
- live_score (with H1/H3): 9.0
- live_no_h1h3_score: 31.0
- raw_delta: 6.9 (basic scoring already differs by 6.9 points)

## Implication
- Refactor to single source of truth will change backtest scores significantly.
- Existing backtest tests asserting specific scores will break and need updating.
- Walk-forward results will change.
- CSV: results/backtest_parity_gap.csv