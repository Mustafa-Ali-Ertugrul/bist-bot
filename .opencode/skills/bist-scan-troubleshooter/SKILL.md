---
name: bist-scan-troubleshooter
description: Diagnose BIST scan issues across fetch, filter, scoring, persistence, and UI display.
---

Use this skill when:
- scans hang or return empty
- scanned count and displayed count diverge
- signals disappear after successful fetch
- background scan behaves differently from UI scan
- scans fire outside market hours

Investigate in order — each stage maps to a real module:

1. **Provider fetch** — `src/bist_bot/data/fetcher.py`, `data/providers.py` (failover router with circuit breaker, `FAILOVER_FAILURE_THRESHOLD=3`), `data/scraper.py`. Check `DATA_PROVIDER` (default `yfinance`; `official_stub` for tests; `official` for Matriks/Foreks/Finnet). 401/429/5xx retry; 4xx fails fast.
2. **Scheduler / timeout path** — `scheduler.py` + `market_calendar.py` (session 10:00–18:00 TR=UTC+3, continuous close buffer; holiday calendar valid until 2030). `SCAN_INTERVAL_MINUTES` default 15. Worker health surface is `worker_http.py` (`/healthz` liveness, `/readyz` scan-age, `/metrics`). Streamlit background scans: `STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS`.
3. **Filtering stages** — `strategy/engine_filters.py`; check the rejection breakdown payload (surfaced via `/api/scans/history`) before suspecting data loss.
4. **Scoring thresholds** — `strategy/engine.py`, `strategy/scoring.py`, `strategy/params.py` (48/20/8/-8/-20/-48 by default).
5. **Persistence** — `scanner.py` enforces a single complete-scan transaction/lock; repositories live in `db/repositories/signals_repository.py`. Check `SIGNAL_TTL_MINUTES` (default 60) — expired signals are kept with `is_expired=true` but not notified.
6. **API payload** — `dashboard.py` routes: `/api/scan`, `/api/analyze/<ticker>`, `/api/signals/history`, `/api/scans/history`, `/api/stats`.
7. **UI rendering** — `ui/runtime_scan.py`, `ui/runtime_data.py`, `ui/pages/scan_detail_page.py`, `ui/pages/signals_page.py`. UI has its own session cooldown (`ui/session_cooldown.py`, `STREAMLIT_SCAN_COOLDOWN_SECONDS`) — not a backend failure.

Output:
- exact failing stage (with file path)
- likely cause
- minimal safe fix
- how to prove it (targeted pytest, e.g. `tests/test_data_fetcher*.py`, `tests/test_scanner*.py` — run with `PYTHONPATH=src`)
