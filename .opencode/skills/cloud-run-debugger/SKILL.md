---
name: cloud-run-debugger
description: Diagnose Cloud Run issues involving startup, session, routing, env vars, and timeouts.
---

Deployment shape (README + `cloudrun/`):
- TWO services, never one: `bist-bot-api` (Flask JSON API, `python dashboard.py`) and `bist-bot-ui` (Streamlit).
- Manifests: `cloudrun/api-service.yaml`, `cloudrun/ui-service.yaml`; deploy script `cloudrun/deploy.ps1` (PowerShell).
- UI needs `API_BASE_URL` → API service URL; API needs `CORS_ORIGINS` → UI service URL (no `*` default).
- Both need `DB_PATH=/tmp/bist_signals.db` for ephemeral/demo, or `DATABASE_URL` (Cloud SQL) for persistence — the Cloud SQL instance must be attached to both services so login/register data is shared.
- `JWT_SECRET_KEY` via Secret Manager; `RATE_LIMIT_STORAGE_URI=memory://` only for single-instance demo.

Use this skill when:
- login works locally but not in Cloud Run
- requests time out in production
- UI/API behave inconsistently after deploy
- revisions behave differently

Check in order:
1. **Env var drift** — settings live in `src/bist_bot/config/settings.py` + `subsettings.py`; env names accept `BIST_BOT_` prefix aliases. Compare revision envs: `gcloud run services describe <svc> --format=yaml`.
2. **Timeouts / cold start** — Streamlit needs `STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS` (default 180) and `API_REQUEST_TIMEOUT_SECONDS` (45).
3. **Health surfaces** — API: `/health`, `/ready`, `/metrics` (`dashboard.py`; healthchecks must not hit restart loops — see the comment in `dashboard.py` near "Docker/Cloud Run healthchecks"). Worker: `/healthz`, `/readyz`, `/metrics` (`worker_http.py`).
4. **Auth/session storage model** — auth is DB-backed (`users` table); env bootstrap only seeds the FIRST admin when the table is empty. Old `ADMIN_EMAIL`/`ADMIN_PASSWORD_HASH` env names are dead — only `ADMIN_BOOTSTRAP_EMAIL`/`ADMIN_BOOTSTRAP_PASSWORD_HASH` are read.
5. **Service-to-service URL mismatch** — `API_BASE_URL` vs `CORS_ORIGINS` must reference each other's Cloud Run URLs, not localhost.

Output:
- symptom
- probable cause
- evidence path
- smallest safe remediation
- deploy verification (gcloud command + which endpoint to curl)
