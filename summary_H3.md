## Objective
- Add `--counter-trend-multiplier` CLI override to walk-forward scripts.
- Implement H3 chase (overextended) blocking in `calculate_score_and_reasons` as a `min()/max()` override (not penalty), to defeat clamp saturation. Conservative profile fully blocks (cap=10); strong-trend exception gets relaxed cap (20). Kill-switch via `chase_block_enabled=False`.

## Important Details
- **Stratejiye minimal dokunma** — only modifications: `params.py` (6 new fields + conservative overrides), `engine_filters.py` (one new block between momentum-check and ±100 clamp).
- Chase veto = `min(score, cap)` / `max(score, -cap)` — does NOT use additive penalties. This bypasses the existing ±100 saturation observed in H3 root-cause (penalty-based penalties would have been eaten by ±100 clamp).
- overextended_long: `(bb_pos=="ABOVE_UPPER") OR (cci > chase_cci_threshold) OR (dist_resist_pct < chase_resist_pct)`. Short symmetric.
- strong_trend_ride requires **all three**: `adx > chase_strong_trend_adx` AND `trend_dir != 0` AND `trend_dir == momentum_dir`. Cap then relaxed, NOT removed.
- chase_block_enabled=False → entire H3 block skipped (kill-switch for backward compat).
- Conservative profile: `chase_blocked_score_cap=10` (below buy_threshold=25 → no buy signal can fire); `chase_strong_trend_cap=20` (still below buy_threshold → only RADAR neighbors).

## Work State
### Completed
- **H11 (timestamp UTC fix):** already done before this session.
- **H1 (counter-trend alignment gating):** already done before this session.
- **`--counter-trend-multiplier` CLI override:** already done before this session; BIST30 two-suite comparison showed scores identical between ctm=0.0 and 0.3 on conservative+BIST30 (H1 dormant on those data).
- **test_agent_rules fixture fix:** test fixture `TradingAgent(pm, es, cb, db, notifier, settings)` was missing `execution_service=es`, so the agent built its own ExecutionService and ignored the mock. Adding `execution_service=es` made all 5 tests pass.
- **H3 implementation:**
  - `StrategyParams`: added 6 fields (`chase_block_enabled`, `chase_cci_threshold=150`, `chase_resist_pct=1.5`, `chase_strong_trend_adx=30`, `chase_blocked_score_cap=20`, `chase_strong_trend_cap=30`). `conservative()` overrides cap=10 / strong_cap=20.
  - `calculate_score_and_reasons`: added H3 veto block AFTER H1 gating + sideways + momentum-check, BEFORE ±100 clamp. Symmetric for shorts.
  - `tests/test_h3_chase.py`: 16 tests across 6 classes — (a) conservative+default short cap test, (b) strong-trend-ride, (c) no-overextended → unchanged, (d) kill-switch, (e) symmetric short side, (f) cap-value assertions.
  - All **133/133** tests pass across strategy/risk/signal/H1/H3 suite.
  - **Ruff**: All checks passed on production code (`src/bist_bot/strategy/`) and on `tests/test_h3_chase.py`.

### Active
- *(none)* — implementation + verification complete.

### Blocked
- *(none)*

## Verification
- `pytest tests/test_h3_chase.py` → **16/16 PASS**
- `pytest tests/test_h1_alignment.py tests/test_h3_chase.py tests/test_strategy_scoring_regression.py tests/test_strategy_engine_integration.py tests/test_strategy.py tests/test_strategy_params_conservative.py tests/test_strategy_regime_adx.py tests/test_signal_timestamp.py tests/test_signal_models_fixes.py tests/test_signal_expiration.py tests/test_walk_forward_validation.py` → **133/133 PASS**
- `ruff check src/bist_bot/strategy/ tests/test_h3_chase.py` → **All checks passed**

## Conservative profile ATEŞ testi (live confirmation)
`tests/test_h3_chase.py::TestChaseVetoConservative::test_chase_blocked_to_conservative_cap` ASSERTS that a chase scenario (CCI 198 + BB ABOVE_UPPER + direnç 0.5% + ADX 20, ham skor +55) **drops to exactly 10** when run with `StrategyParams.conservative()`. This is the live evidence that H3 fires (`chase_block_enabled=True`) and tightens the cap to 10 in conservative profile.

## Pre-existing failures (NOT caused by H3)
- 19 pre-existing failures in `tests/test_db.py`, `test_database_manager.py`, `test_db_postgres.py`, `test_integration_flows.py`, `test_observability.py`, `test_paper_trade_service.py` → H11 timestamp regression (naive datetimes in fixtures).
- 7 in `test_login_response_handling.py` → Turkish locale (ı ↔ i) mismatch.
- 2 in `test_data_fetcher.py` → BIST100 watchlist drift.
All pre-existed my changes; H3 changes touch only `params.py` + `engine_filters.py` + `test_h3_chase.py`.

## Next Move
1. User runs WF (walk-forward) to measure H3 effect on BIST30 baseline.
2. Report will include:
   > "baseline (H3 kapalı) conservative stress: medyan OOS ~+0.91%, overfitting ~%43, robust=10, pozitif OOS ~%61, bottom listesinde SASA -3.0 (chase). H3 sonrası bu dördü + SASA'nın akıbeti ölçülecek."
3. If WF improves OOS as expected, H3 stays. If not, kill-switch via `chase_block_enabled=False` (no edit to scoring.py).

## Relevant Files
- `src/bist_bot/strategy/params.py` — added H3 fields + conservative overrides.
- `src/bist_bot/strategy/engine_filters.py` — added H3 veto block (lines 196-276 area, between momentum-check and ±100 clamp).
- `tests/test_h3_chase.py` — new, 16 tests.
- `tests/test_agent_rules.py` — fixed `execution_service=es` (1-liner).
- `tests/test_h1_alignment.py` — untouched, still PASS.
- `src/bist_bot/strategy/scoring.py` — **untouched** (per task rules forbidding weight touching).