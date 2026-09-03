---
name: financial-data-validation
description: Validate financial market data quality, freshness, continuity, and provider behavior.
---

Data layer map (`src/bist_bot/data/`):
- `fetcher.py` — fetch orchestration + metrics counters
- `providers.py` — `yfinance` (default), `official_stub` (tests), `official` REST adapter (Matriks/Foreks/Finnet via `OFFICIAL_*` envs; 401/429/5xx auto-retry, 4xx fast-fail), failover router with circuit breaker
- `scraper.py` — BIST scraping fallback (rate-limit prone)
- `bist100.py`, `us_universe.py` — static ticker lists
- `universe/` — point-in-time JSON snapshots; `universe.py::get_universe_for_date(date)` resolves the nearest past snapshot, warns and falls back to current watchlist when missing

Use this skill when:
- scan results look too sparse
- chart data has gaps
- provider reliability is in doubt
- derived indicators may be using incomplete inputs

Check:
- required OHLCV columns
- monotonic dates, duplicate rows, stale last-bar dates
- missing intervals / session gaps (market hours 10:00–18:00 TR=UTC+3, no DST in Turkey since 2016 — `market_calendar.py`)
- timezone assumptions (store/compare in TR-aware datetimes, not naive)
- symbol formatting (`.IS` suffix for yfinance BIST symbols)
- fallback behavior (failover order, circuit-breaker state, universe snapshot fallback)
- known limits: yfinance is 15-min delayed for BIST; rate limits → 429; survivorship bias for delisted tickers in backtests

Output:
- data quality findings
- likely impact on signals
- code hotspots (file paths)
- concrete remediation
- recommended tests (`tests/test_data_fetcher*.py`, `tests/test_provider*.py` — run with `PYTHONPATH=src`)
