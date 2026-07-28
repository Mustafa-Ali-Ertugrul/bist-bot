# Task Plan: H3 — Chase (Aşırı Uzama) Blokajı

## Goal
Add chase (overextended) blocking to `calculate_score_and_reasons` using min/max override (not penalty points) so that extended positions in overbought territory don't generate buy signals. Conservative profile fully blocks (cap=10), strong-trend exceptions get relaxed cap (20). Kill-switch available via `chase_block_enabled=False`.

## Phases
- [x] Phase 1: Read params, scoring, engine_filters, test files, audit doc
- [x] Phase 2: Plan and confirm approach
- [ ] Phase 3: Add H3 fields to StrategyParams (base defaults + conservative)
- [ ] Phase 4: Implement chase veto in calculate_score_and_reasons (min/max override)
- [ ] Phase 5: Create tests/test_h3_chase.py (6 test cases)
- [ ] Phase 6: Run full strategy/risk/signal/H1/H3 suite + ruff
- [ ] Phase 7: Update anchored summary

## Key Design Decisions
1. Chase veto = min()/max() override, NOT score penalty. This defeats clamp saturation.
2. Applied AFTER H1 gating + sideways damping, BEFORE clamp(±100).
3. overextended_long: (bb_pos=="ABOVE_UPPER") OR (cci > chase_cci_threshold) OR (dist_resist_pct < chase_resist_pct)
4. overextended_short: (bb_pos=="BELOW_LOWER") OR (cci < -chase_cci_threshold) OR (dist_support_pct < chase_resist_pct)
5. strong_trend_ride: (adx > chase_strong_trend_adx) AND (trend_dir != 0) AND (trend_dir == momentum_dir)
6. Default caps: blocked=20, strong_trend_cap=30. Conservative: blocked=10, strong_trend_cap=20.

## Risks
- None of the existing regression fixtures trigger chase (score positive + ABOVE_UPPER / CCI>150 / resist<1.5) — so no expected value changes needed.
- H3 is independent of H1 (works on different field, no overlap).