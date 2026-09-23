# AppSec Finding #21: Rate-limit key IP collapse behind Cloud Run

Date: 2026-09-21
Related: `docs/security/phase0_phase1_report.md` (Round 17 auth rate-limit key,
"Proxy/XFF and concurrency" section), `tests/test_auth_ratelimit_key.py`
Status: **Layer 1 active (JWT-keyed buckets) / Layer 2 CLOSED-N/A** — Cloud Run
deploy path retired 2026-09-23 (`chore/retire-cloud-run`); TRUSTED_PROXY_HOPS
stays 0 everywhere. Re-open Layer 2 only if a trusted reverse-proxy deployment
returns, and only after live XFF-chain verification (runbook below).

> **Kapatma notu (2026-09-23):** GCP projesi faturalandırması kapalıydı; deploy'lar
> 12 Eylül'den beri billing hatasıyla düşüyor ve servis 503 dönüyordu. Cloud Run
> pipeline'ı repodan kaldırıldı (workflow, manifestler, deploy.ps1, README
> talimatları). Layer 2'nin hedefi (Google front-end'in XFF zinciri) artık yok;
> kompozisyon/lokal dağıtımda `TRUSTED_PROXY_HOPS>0` ASLA ayarlanmaz (aşağıdaki
> uyarı). Layer 1 (doğrulanmış JWT kimliğiyle per-user bucket'lar) kodda aktif
> kalır ve anonim istekler için yeterli korumadır (401 dönerler).

## Finding

Flask-Limiter keys every limit on `get_remote_address()` (`request.remote_addr`).
Gunicorn sets `REMOTE_ADDR` from the TCP peer only — `X-Forwarded-For` never
rewrites it (verified against installed gunicorn 26.x source; no ProxyFix in
this app). On Cloud Run the TCP peer is Google's front-end proxy, so **all
clients collapse to one (or very few) shared `remote_addr` values**.

Affected limits (all keyed on the collapsed IP before this fix):

| Endpoint | Limit | Key before fix |
|---|---|---|
| global default (incl. `/ui/*` renders) | 60/min | shared bucket |
| `POST /api/scan` | 10/min | shared bucket |
| `POST /api/orders/intents/<client_id>/resolve` | 10/min | shared bucket |
| `POST /api/billing/claim` | 10/min | shared bucket |
| `POST /api/auth/session` | 10/min | shared bucket |
| `GET /api/analyze/<ticker>` | 30/min | shared bucket |
| `GET /api/signals/history` | 60/min | shared bucket |

Not affected: `/api/auth/login`, `/api/auth/register` — already bound to
`remote_addr:email` (Round 17); the email component is the real per-account
throttle.

Impact:
1. The global 60/min default becomes one bucket shared by **all** users — one
   busy user can lock everyone out (DoS).
2. Financially material endpoints (`/api/scan`, order-intent resolve) share the
   same collapse — during a reconciliation emergency one trader's traffic can
   block another's.
3. Probes and health checks originate from (different) fixed IPs and also draw
   from fixed buckets.

## Fix

### Layer 1 — per-user buckets via verified JWT identity (deployed in code)

`src/bist_bot/dashboard.py`: new module-level key
`_client_rate_limit_key()` and `Limiter(_client_rate_limit_key, ...)`
(the constructor key_func governs `default_limits` and every route limit
that does not override `key_func`).

- Identity comes from `verify_jwt_in_request(optional=True)` — HMAC signature,
  expiry, and JTI blocklist verified. Never parse the raw Authorization
  header: unverified identity would let attackers rotate fake identities to
  evade every bucket.
- Runs in flask-limiter's `before_request`, before the route's
  `@jwt_required()` — hence optional self-verification (same pattern as
  `api_auth_logout`).
- Broad except: expired/invalid/revoked tokens and cookie-CSRF errors fall
  back to the IP bucket; the route still returns the proper 401/422.
- Login/register keep `_auth_rate_limit_key` (email+IP) unchanged.

Regression tests: `tests/test_client_ratelimit_key.py`.

### Layer 2 — opt-in ProxyFix for the anonymous remainder (gated)

`TRUSTED_PROXY_HOPS` (default **0**) in `ServerSettings`
(`src/bist_bot/config/subsettings.py`); applied in
`src/bist_bot/wsgi.py::build_wsgi_app` as `ProxyFix(app, x_for=hops)`
(`x_for` only — forwarded scheme is already trusted by gunicorn's
`--forwarded-allow-ips=*` on Cloud Run).

- `0` keeps current behavior everywhere (compose/local/tests): `REMOTE_ADDR`
  stays the TCP peer; client-sent XFF can never move a request to another
  bucket.
- ~~Cloud Run artifacts pin `TRUSTED_PROXY_HOPS=0` with parity tests~~ —
  bu artefaktlar (`cloudrun/api-service.yaml`, deploy workflow'u,
  `cloudrun/deploy.ps1`, `tests/test_manifest_hardening.py`) 2026-09-23'te
  Cloud Run emekliliğiyle birlikte repodan silindi (bkz. üstteki kapatma notu).

### Runbook before flipping to 1 (honors the phase report's constraint)

1. Deploy to Cloud Run with `TRUSTED_PROXY_HOPS=0`.
2. Capture one real request's `X-Forwarded-For` chain (temporary debug log or
   `gcloud` request logs).
3. Confirm the **rightmost** entry is the true client IP as seen by Google's
   edge (client-supplied forged entries appear to the left; a rightmost
   internal IP means extra hops exist).
4. Set `TRUSTED_PROXY_HOPS=1` in all four deploy artifacts and redeploy.
   With exactly one trusted hop, `x_for=1` is spoof-resistant: the client
   cannot add or remove anything right of Google's appended entry.

Residual (until step 4): anonymous requests (login/register excepted — they
are email-bound) still share collapsed IP buckets. Security impact is nil —
anonymous callers receive 401 from the route anyway.

Never set `TRUSTED_PROXY_HOPS>0` on deployments where clients connect
directly (compose/local) — clients could then spoof `REMOTE_ADDR` via XFF.

## Verification

- `uv run pytest tests/test_client_ratelimit_key.py tests/test_auth_ratelimit_key.py tests/test_manifest_hardening.py -q` — 18 passed.
- Full suite: 1828 passed, 2 skipped (Postgres unavailable in this environment).
- `uv run ruff check .` — clean; `uv run --locked mypy src/bist_bot --ignore-missing-imports` —
  165 files, no issues.
