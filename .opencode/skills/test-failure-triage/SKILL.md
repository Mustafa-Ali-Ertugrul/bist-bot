---
name: test-failure-triage
description: Triage failing tests with a minimal-fix mindset.
---

Use this skill when:
- CI fails (`.github/workflows/ci.yml` — lint/test/security/docker/deploy jobs)
- new tests are flaky
- a production fix broke existing behavior

Repo test facts:
- 125+ test files under `tests/` (pytest; `pyproject.toml` sets `testpaths`, `--strict-markers`, `-ra`).
- Markers: `slow` (deselect with `-m "not slow"`), `integration` (external services required).
- Shared fixtures: `tests/conftest.py`.
- Run from repo root with `PYTHONPATH=src` (or activate the venv where the package is installed).
- Windows note: the shell is PowerShell 5.1 — use `$env:PYTHONPATH="src"; python -m pytest ...` instead of `export`/`&&` chains.

Approach:
- classify failure: logic / environment (env vars, network, DB) / brittle expectation / ordering / timing (market-hour gating in `scheduler.py`, cooldowns)
- isolate the smallest reproducer:
  ```powershell
  $env:PYTHONPATH="src"; python -m pytest tests/test_backtest.py -v
  $env:PYTHONPATH="src"; python -m pytest -m "not slow and not integration"
  ```
- decide whether code or test is wrong (prefer trusting production code unless the test encodes a contract documented in README/docs)
- propose the smallest correct change

High-signal test areas for triage:
- backtest parity: `test_backtest_strategy_parity.py`, `test_backtest_vectorized.py` (vectorized vs iterative must agree)
- walk-forward: `test_walk_forward_validation.py`, `test_backtest_walkforward.py`
- providers: `test_data_fetcher*.py`, provider failover tests
- risk: `test_circuit_breaker.py`
- DB: `test_db.py`, `test_db_postgres.py`, `test_data_layer_integration.py`
- API: `test_healthcheck.py`, `test_api_responsiveness.py`

Output:
- failure class
- root cause
- fix recommendation
- regression risk
