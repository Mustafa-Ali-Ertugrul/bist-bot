---
name: python-project-stabilizer
description: Stabilize Python applications with minimal-risk fixes and targeted validation.
---

Use this skill when:
- a Python service is flaky
- production behavior differs from local
- a bug likely involves config/runtime/test mismatch

Do not use when:
- the task is purely architectural
- the request is only for high-level brainstorming

Repo facts:
- Entry points: `main.py` (bot + scheduler + optional Flask dashboard), `dashboard.py` (standalone Flask), `streamlit_app.py` (operator UI), `python main.py --worker` (scanner/scheduler only).
- Config: `src/bist_bot/config/settings.py` + `subsettings.py` + `watchlist.py` + `store.py` (UI preference store). Env vars accept `BIST_BOT_` prefix aliases. Malformed env values are reported (fail-loud on critical ones).
- DI container: `dependencies.py::AppContainer` wires fetcher/engine/executor/notifier per `BROKER_PROVIDER` (`paper` default, `algolab`, or `live` broker facade).
- Logging/metrics: `app_logging.py` (JSON via `LOG_FORMAT=json`), `app_metrics.py` + `observability/metrics.py` (Prometheus text format, thread-safe registry).
- Stack: Python 3.11+, SQLAlchemy 2.x, Flask + JWT, Streamlit, APScheduler-style scheduler loop, pytest + ruff (`pyproject.toml`).

Checklist:
1. Identify the failing entrypoint (`--once`, `--worker`, dashboard, streamlit).
2. Inspect config loading path (`config/settings.py`) — check env aliases and validation errors first.
3. Inspect runtime assumptions (thread/process model, scheduler market-hour gating, cooldowns).
4. Prefer minimal diff — see AGENTS.md high-risk paths: `db/`, `config/`, `ui/runtime*.py`, `scanner.py`, `cloudrun/`, `.github/workflows/`.
5. Run targeted checks first:
   ```powershell
   $env:PYTHONPATH="src"; python -m pytest tests/test_<area>.py -v
   ruff check . --isolated
   ```
6. State residual risk.

Focus areas:
- environment loading / prefix aliases
- retries/timeouts (provider failover, circuit breaker)
- thread/process assumptions (scanner lock, metrics registry thread-safety)
- serialization boundaries (Flask API ↔ Streamlit UI payloads)
- test coverage gaps

Output:
- root cause
- smallest safe fix
- validation commands
- follow-up hardening
