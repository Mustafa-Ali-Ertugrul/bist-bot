# AppSec Phase 0 / Phase 1 Evidence Report

Date: 2026-09-04
Branch: `feat/post-pr118-security-hardening`

## Executive status

- Baseline score: **73.5**
- Current open score: **58.0** (`results/security/phase1.json`)
- Fixed baseline findings: **#2, #4, #20**
- Warn-only and still scored open: **#1 RBAC, #3 artifact trust**
- Deployment blocker: leaked historical API key must be rotated before any push/deploy.

## Runtime configuration observed

Only non-secret metadata was printed.

| Setting | Observed |
|---|---|
| Broker mode/provider | `paper` / `paper` |
| AlgoLab dry-run | `true` |
| `AUTO_EXECUTE` / independent gate | `false` / `false` |
| RBAC mode | `warn` |
| Public registration | `false` |
| Calibrator trust | `warn` |
| Model signing private key configured | no |
| Model verification public key configured | no |
| Effective DB backend | PostgreSQL (`postgres` Docker hostname) |
| Rate-limit storage | `memory://` |
| Declared instance count | 1 |
| Gunicorn | 1 worker, 8 threads, 330-second timeout |

Cloud Run is now explicitly capped at one instance while process-local rate limiting and scan
locking remain. Scaling beyond one instance requires Redis-backed limiting/locking first.

## Role distribution

The host cannot resolve the Compose-only `postgres` hostname, so the query was executed read-only
inside the healthy `bist-bot-postgres` container.

| Role | Count |
|---|---:|
| `admin` | 2 |
| `trader` | 0 |
| `user` | 0 |

Privileged rows: user IDs `1` and `4`, both `admin`, created on 2026-08-12 and 2026-08-13.
Their provenance cannot be inferred from the row alone; both require maintainer confirmation before
`RBAC_MODE=enforce`. No accounts were demoted automatically.

## HTTP route inventory

| Route | Auth | Classification | Notes |
|---|---|---|---|
| `GET /livez` | none | read/liveness | process-only probe |
| `GET /ready`, `GET /readyz` | none | read/readiness | currently shares detailed health behavior |
| `GET /health` | none | read + broker side effect | still open finding #10 |
| `GET /metrics` | JWT unless `METRICS_PUBLIC` | read | no write side effect |
| `POST /api/auth/login` | rate limited | auth write | issues 15-minute access token |
| `POST /api/auth/register` | config gate + rate limited | DB write | disabled by default; always creates `user` |
| `POST /api/scan` | JWT + admin/trader RBAC | side effect | persistence, notifications, optional execution |
| `POST /api/orders/intents/<id>/resolve` | JWT + admin/trader RBAC | financial state write | explicit manual reconciliation/unlock |
| `GET /api/analyze/<ticker>` | JWT | read/cache write | no broker action |
| `GET /api/signals/history` | JWT | read | none |
| `GET /api/stats` | JWT | read | none |
| `GET /api/scans/history` | JWT | read | none |

No other Flask routes were found under `src/`.

## JWT compatibility and lifecycle

- `get_jwt_identity` occurs only in `dashboard.py`: the RBAC lookup and manual-resolution audit.
- New tokens use numeric user ID strings and include role/email claims.
- Legacy email-identity tokens cannot be converted to an integer; the RBAC lookup returns `None`.
  In enforce mode this produces **403**, not 500; this is covered by `test_scan_authz.py`.
- In warn mode legacy/unauthorized scan requests are logged but their `ScanService` receives
  `AUTO_EXECUTE=false` and `AUTO_EXECUTE_ENABLED=false`.
- There is no refresh-token implementation in `src/`; no refresh-role path exists.
- Existing pre-deployment tokens expire under their original one-hour TTL. A deployment therefore
  has at most a one-hour compatibility window; users may need to log in again.

## RBAC/bootstrap evidence

- `ALLOW_PUBLIC_REGISTRATION=false` by default and is tested.
- New registrations always receive `user`.
- `AUTO_EXECUTE_ENABLED=false` is an independent scanner-level gate; `AUTO_EXECUTE=true` alone is
  insufficient.
- Bootstrap inserts `admin`; explicit `ADMIN_BOOTSTRAP_UPDATE_EXISTING=true` also promotes the
  configured existing account to admin.
- Enforce startup fails if no `admin` or `trader` exists.
- RBAC allow/warn/deny and manual resolution events are written both to structured logs and the
  DB-backed `audit_trail`, including user ID, claim role, DB role, route, and request ID.

## AlgoLab contract and reconciliation

- Public GitHub code search found no independent AlgoLab implementation documenting
  `client_order_id`; the only result was this repository.
- `ALGOLAB_SEND_CLIENT_ID=false` by default. It must remain false until vendor documentation or a
  controlled one-lot closed-market rejection test verifies unknown-field behavior. The test must
  confirm both request acceptance/rejection semantics and whether the field is echoed by history.
- Timeout/5xx does not retry place-order POST.
- Reconciliation requires `ALGOLAB_ORDER_HISTORY_URL` and searches the day's complete order history,
  including filled/cancelled/open states.
- Match order: exact echoed client ID (only when enabled), then
  `(ticker, side, quantity, order_type, price, stop_price, submitted_at ± 180 seconds)`.
- Missing history, no match, or multiple matches remains `unknown`; the symbol lock stays active and
  a critical operator alert is emitted.
- Manual admin/trader resolution is required to release that lock.
- Live AlgoLab refuses startup without non-SQLite `DATABASE_URL`, credentials, confirmation, and
  required endpoint configuration.

## Deserialization inventory

Static search patterns: `pickle.load`, `joblib.load`, `torch.load`, `yaml.load(`.

| Location | Status |
|---|---|
| `src/bist_bot/ml/meta_model.py` model joblib fallback | allowed only after manifest checks; enforce requires signed manifest |
| `src/bist_bot/ml/meta_model.py` legacy calibrator joblib | warn-mode migration only; enforce requires JSON |
| `scripts/migrate_calibrator.py` | operator-only; mandatory approved SHA-256 before load |
| pickle / torch / unsafe yaml | no matches |

Observed legacy calibrator hashes (inventory only, **not provenance approval**):

- `models/latest-local/probability_calibrator.joblib`: `300017893CE8BBDB0493F5097301940DDB51E4221501E51699F77AAEE323CF8A`
- `models/local-run/probability_calibrator.joblib`: `9A793F7B1E557E7905F2F013168F220FF86CFF7E88488D76755CA36761AE2D82`

No independent known-good hash or signing record exists. These artifacts must be retrained or have
their provenance approved out of band before conversion. `CALIBRATOR_TRUST=off` is rejected.

Private signing key delivery: `MODEL_SIGNING_PRIVATE_KEY_FILE` on the training/CI host only.
Public verification key delivery: `MODEL_VERIFY_PUBLIC_KEY_FILE` mounted into runtime.
Neither is currently configured in the observed environment.

## Build and dependency answers

- Python base image is digest pinned.
- uv helper image is version + digest pinned.
- `--no-install-project` is intentional: source is copied to `/app/src` and Docker sets
  `PYTHONPATH=/app/src`.
- CI runs `uv sync --locked`; a stale lock fails.
- CI audits the hash-bearing `requirements.lock.txt` and fails when either generated requirements
  export differs from the locked uv export.

## Proxy/XFF and concurrency

- Gunicorn: one process, eight threads.
- Cloud Run manifest/deploy paths now specify max one instance.
- Cloud Run request timeout is 360 seconds; Gunicorn worker timeout is 330 seconds and the scan
  timeout is 300 seconds.
- Gunicorn trusts forwarded scheme headers only in the Cloud Run command, where ingress terminates
  at the managed proxy. Local Compose does not enable wildcard forwarded-header trust.
- `ProxyFix` is not installed and no production request capture was available, so XFF hop count was
  **not measured**. Do not enable ProxyFix until a trusted Cloud Run/LB request confirms the chain.
- `RATE_LIMIT_STORAGE_URI=memory://`; it is acceptable only while max instance count remains one.

## Secret incident scope

- Repository visibility: **public**.
- GitHub reports **1 fork**; compromise must be assumed.
- History finding: `opencode.json:26`, commit `6d0fa86e194708840f26d6a91447d0813a25c184`.
- `opencode.json` is removed from the Git index and added to `.gitignore` and `.dockerignore`; the
  local file is retained.
- No-git scan found four redacted findings in the local ignored `.env`; no findings were reported
  under `src`, `scripts`, `cloudrun`, `.github`, or `android_app`. Secret values were not inspected.
- Artifact Registry inventory failed because billing is disabled for the configured GCP project;
  old image deletion remains blocked.
- Rotation, provider usage/billing review, fork notification, history rewrite, GitHub cache cleanup,
  and collaborator reclone remain owner actions.

## Enforcement gates

Do not set `RBAC_MODE=enforce` until user IDs 1 and 4 are confirmed as intended admins.
Do not set `CALIBRATOR_TRUST=enforce` until newly trained JSON artifacts are signed and the runtime
public key mount is verified.
