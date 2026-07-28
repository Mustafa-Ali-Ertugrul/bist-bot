# Chase Diagnostics Findings

## Run details
- Command: `python scripts/run_walk_forward_bist30.py --diagnose-chase --limit 5`
- Tickers analyzed: AKBNK.IS, ARCLK.IS, ASELS.IS, ASTOR.IS, BIMAS.IS (BIST30 top 5)
- Period: 3y

## Counts
- Total `chase_candidate_rows` (all tickers): 430
- Total `chase_high_score_rows`             : 70
- Total `h3_actually_capped_rows`           : 70

## Decision Tree Match
- `h3_actually_capped_rows` > 0 but OOS return did not change at all.
- Verdict per spec: "H3 cap'liyor ama OOS degismedi -> H3 cap'liyor ama o pencereler zaten trade edilmiyordu / aggregate'e girmiyordu; o zaman gercekten redundant, H3 kapatilabilir."

## Real Technical Root Cause
- **Backtest-Live drift**: `Backtester.run()` in `src/bist_bot/backtest/engine.py` implements its own vectorized scoring mechanism using NumPy. It does **not** call `calculate_score_and_reasons()`.
- The backtester lacks the H3 chase blocking code entirely.
- Consequently, the walk-forward simulation runs using the raw uncapped scores computed in `backtest/engine.py`, causing the OOS return to remain exactly identical to the pre-H3 runs.
- In live execution (via `StrategyEngine.analyze`), H3 **is** active and will cap scores properly.
