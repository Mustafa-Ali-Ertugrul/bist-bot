# AppSec Phase 0 / Phase 1 Evidence Report

Date: 2026-09-04
Branch: `feat/post-pr118-security-hardening`

## Executive status

- Baseline score: **73.5**
- Current open score: **51.0** (`results/security/phase1.json`, schema v2)
- Scoring criteria: **fixed/accepted x0.0, mitigated_warn x0.5, open x1.0**.
  Warn-only mitigations stay partially open until enforcement is deployed.
- Fixed baseline findings: **#2, #4, #20**
- Partially mitigated (half weight): **#1 RBAC, #3 artifact trust**
- Deployment blocker: leaked historical API key must be rotated before any push/deploy.

## Environments actually observed

The only running environment inspected during this audit was the **local Docker Compose stack**:
API, UI, scanner worker, PostgreSQL, Prometheus, and Grafana containers were running on the audit
workstation. The role inventory below came from that local Compose PostgreSQL container, not from a
production database. Its `BROKER_MODE`/provider were `paper`/`paper`, both auto-execute flags were
false, registration was disabled, RBAC was `warn`, and rate limiting used `memory://`.

No serving Google Cloud production environment was observed. The configured gcloud project reports
billing disabled, so Artifact Registry and Cloud Run runtime inventory could not be queried. Values
such as one instance, one Gunicorn worker, ephemeral `/tmp` SQLite, and 360-second request timeout
describe the **checked-in Cloud Run deployment profile**, not measured production state. Therefore
there is currently no production role inventory and `RBAC_MODE=enforce` must not be enabled based on
the local user rows alone.

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

Privileged rows in the local Compose DB: user IDs `1` and `4`, both `admin`, created on 2026-08-12
and 2026-08-13. IDs 2 and 3 are absent; the schema has no soft-delete/audit evidence that can
distinguish deleted users from sequence gaps or prior test data. Their provenance cannot be inferred
from the current rows. No accounts were demoted automatically.

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
| `POST /api/orders/intents/<id>/resolve` | JWT + **admin-only** RBAC + strict confirmation schema | financial state write | manual reconciliation/unlock; requires reason ≥10 chars, `confirmed_in_broker_ui: true`, `broker_order_id` for ack; rejected logs at error/critical severity |
| `GET /api/analyze/<ticker>` | JWT | read/cache write | no broker action |
| `GET /api/signals/history` | JWT | read | none |
| `GET /api/stats` | JWT | read | none |
| `GET /api/scans/history` | JWT | read | none |

No other Flask routes were found under `src/`. Side-effect coverage: every route that can
move money or mutate financial reconciliation state (`/api/scan`, `/api/orders/intents/<id>/resolve`)
is under `require_roles`; all remaining routes are read-only, auth-token issuance, or cache writes
with no broker action.

## JWT compatibility and lifecycle

- `get_jwt_identity` occurs only in `dashboard.py`: the RBAC lookup and manual-resolution audit.
- New tokens use numeric user ID strings and include role/email claims.
- Legacy email-identity tokens cannot be converted to an integer; the RBAC lookup returns `None`.
  Unresolved identity returns **401 in both warn and enforce modes** (identity failure, not a role
  failure); this is covered by `test_scan_authz.py`.
- In warn mode legacy/unauthorized scan requests are logged but their `ScanService` receives
  `AUTO_EXECUTE=false` and `AUTO_EXECUTE_ENABLED=false`.
- There is no refresh-token implementation in `src/`; no refresh-role path exists.
- Existing pre-deployment tokens expire under their original one-hour TTL. A deployment therefore
  has at most a one-hour compatibility window; users may need to log in again.

## RBAC/bootstrap evidence

- `ALLOW_PUBLIC_REGISTRATION=false` by default and is tested.
- New registrations always receive `user`.
- `AUTO_EXECUTE_ENABLED=false` is an independent scanner-level gate; `AUTO_EXECUTE=true` alone is
  insufficient. Legacy-only `AUTO_EXECUTE=true` emits a startup warning
  (`auto_execute_disabled_new_gate_required`) and sets the
  `bist_auto_execute_migration_blocked` metric; see `docs/security/auto_execute_migration.md`.
- Bootstrap ordering: legacy migrations → admin seed (from pre-computed
  `ADMIN_BOOTSTRAP_PASSWORD_HASH`, supplied via Secret Manager in production) → privileged-user
  check. Bootstrap create/promote events are written to `audit_trail`.
- An unreachable database raises `DatabaseInitializationError` (distinct from "0 privileged users").
  WSGI degrades to process liveness (`/livez` 200) with `/readyz` and `/health` at 503, so
  orchestrators do not mistake a DB outage for a healthy instance.
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
  History orders already bound to a different intent (`broker_order_id`) are excluded, so a repeated
  signal cannot steal another intent's fill.
- Broker state mapping: `FILLED/PARTIAL/OPEN/SENT` → `ack` (lock held for manual release);
  `CANCELLED/REJECTED` → `rejected` (lock released, order confirmed non-active); unknown raw states
  → `unknown` (lock held).
- Day window uses `Europe/Istanbul` and queries the previous, current, and next Istanbul day around
  the submission instant, so ±180s windows crossing midnight query both days.
- Missing history, no match, or multiple matches remains `unknown`; the symbol lock stays active and
  a critical operator alert is emitted.
- Manual **admin-only** resolution is required to release that lock, with mandatory reason,
  broker-UI confirmation, and `broker_order_id` for ack.
- Live broker startup replays persisted `pending/sent/unknown` intents (`ALGOLAB_RECONCILE_ON_STARTUP=true` default).
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

No independent known-good hash or signing record exists, and no retraining owner/date has been
assigned. These artifacts must be retrained or have their provenance approved out of band before
conversion. Until then `CALIBRATOR_TRUST=warn` leaves CWE-502 partially open by design.
`CALIBRATOR_TRUST=off` is rejected.

Private signing key delivery: `MODEL_SIGNING_PRIVATE_KEY_FILE` on the training/CI host only
(CI secret mount, never committed). Public verification key delivery:
`MODEL_VERIFY_PUBLIC_KEY_FILE` mounted into runtime. Neither is currently configured in the
observed environment. Key rotation: generate a new Ed25519 pair, re-sign all manifests with the new
private key, deploy the new public key to runtime, verify enforce-mode loads, then retire the old
public key; manifests are small JSON files so re-signing is cheap and atomic per artifact directory.

## Build and dependency answers

- Python base image (`python:3.11-slim`) and uv helper image are both version + digest pinned
  (builder and runtime stages).
- `--no-install-project` is intentional: source is copied to `/app/src` and Docker sets
  `PYTHONPATH=/app/src`; no second `uv sync` is needed because `bist_bot` is imported from source.
- CI runs `uv lock --check` (stale lock fails) and fails when either generated requirements export
  differs from the locked uv export (`requirements.lock.txt` and `requirements.txt` both compared
  content-wise against a fresh `uv export`).

## Proxy/XFF and concurrency

- Gunicorn: one process, eight threads, `--timeout 330`, `--graceful-timeout 30`,
  `--forwarded-allow-ips=*` only in the Cloud Run command.
- Auth uses the `Authorization: Bearer` header (no cookie sessions), so there are no secure-cookie
  or HTTPS-redirect loops from forwarded scheme headers.
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
- The raw no-git scan reported 224 redacted candidates: four in the ignored local `.env`, 219 in
  `.venv` dependency files, and one generic-key false-positive candidate in ignored Android IDE
  metadata (`android_app/.idea/planningMode.xml`). No findings were reported under production
  `src`, `scripts`, `cloudrun`, `.github`, or `android_app/app` paths. Secret values were not
  inspected, so it cannot be confirmed from redacted output whether the four `.env` candidates are
  the same credential; rotation must cover the local `.env` as well.
- Public forks are unaffected by a history rewrite; the exposed key must be treated as compromised
  and rotation is the only real fix (rewrite is hygiene).
- Artifact Registry inventory failed because billing is disabled for the configured GCP project;
  old image deletion remains blocked.
- Rotation, provider usage/billing review, fork notification, history rewrite, GitHub cache cleanup,
  and collaborator reclone remain owner actions.

## Enforcement gates

Do not set `RBAC_MODE=enforce` until user IDs 1 and 4 are confirmed as intended admins.
Do not set `CALIBRATOR_TRUST=enforce` until newly trained JSON artifacts are signed and the runtime
public key mount is verified.

## Commit map (foundations commit `5292a7a`)

`5292a7a feat(security): add auth and order safety foundations` is intentionally a shared base, not
a single finding: least-privilege `users.role` default + migration `0003`, `order_intents` schema +
migration `0004` + repository wiring, AlgoLab/client/order-history settings, and the multi-instance
memory-limiter warning. Per-finding behavior and tests live in the follow-up commits
(`d1313a5` F1, `d2be2ba` F2); the foundations commit only enables them.
