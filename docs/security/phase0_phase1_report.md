# AppSec Phase 0 / Phase 1 Evidence Report

Date: 2026-09-04
Branch: `feat/post-pr118-security-hardening`

## Executive status

- Baseline score: **73.5**
- Current open score: **54.5** (`results/security/phase1.json`, schema v2)
- Scoring criteria: **fixed/accepted x0.0, mitigated_warn x0.5, open x1.0**.
  Warn-only mitigations stay partially open until enforcement is deployed.
  Finding #2 (order idempotency) is scored at half-weight (3.5) until vendor dictionary,
  echoed client ID, and `order_intents_unaccounted_open == 0` (gauge of unresolved unaccounted
  locks, not the monotonic counter) are proven in live staging.
- Fixed baseline findings: **#4, #20**
- Partially mitigated (half weight): **#1 RBAC, #2 order idempotency, #3 artifact trust**
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

The application registers routes exclusively via Flask decorators in `dashboard.py`.
No blueprints or dynamic `add_url_rule` registrations exist.

| Method | Route | Auth | Rate Limit | Classification | Notes |
|---|---|---|---|---|---|
| `GET` | `/livez` | none | none | read/liveness | Process-only probe; degrades to worker-exit after `DEGRADED_MAX_SECONDS` |
| `GET` | `/readyz` | none | none | read/readiness | Returns 503 during DB outage; used as container startup probe |
| `GET` | `/ready` | none | none | read/readiness | Legacy alias for `/readyz`; identical behavior |
| `GET` | `/health` | none | none | read + broker probe | Still open finding #10; calls broker authenticate |
| `GET` | `/metrics` | JWT unless `METRICS_PUBLIC` | none | read | Prometheus exposition; no write side effects |
| `POST` | `/api/auth/login` | none | 5 per minute | auth write | Issues 15-minute access token with role claims |
| `POST` | `/api/auth/register` | `ALLOW_PUBLIC_REGISTRATION` | 3 per hour | DB write | Disabled by default; always assigns least-privileged `user` role |
| `POST` | `/api/scan` | JWT + admin/trader RBAC | 10 per minute | financial side effect | Scans market, triggers persistence, notifications, and conditional order execution |
| `POST` | `/api/orders/intents/<id>/resolve` | JWT + **admin-only** RBAC | 10 per minute | financial state write | Manual unlock; strict schema: reason ≥10 chars, `confirmed_in_broker_ui: true`, `broker_order_id` for ack; cross-checked against broker history with 409 Conflict |
| `GET` | `/api/analyze/<ticker>` | JWT | 30 per minute | read / cache write | `force_refresh=true` invalidates cache and triggers upstream provider fetch under rate limit |
| `GET` | `/api/signals/history` | JWT | none | read | Paginated signal history query |
| `GET` | `/api/stats` | JWT | none | read | Aggregated dashboard telemetry |
| `GET` | `/api/scans/history` | JWT | none | read | Historical scan log query |

Side-effect coverage: every route that can move money or mutate financial reconciliation state
(`/api/scan`, `/api/orders/intents/<id>/resolve`) is strictly gated under `require_roles`. All other
routes are read-only, auth issuance, or cache queries. No scheduler-trigger or notifier-test
routes exist.

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
  orchestrators do not mistake a DB outage for a healthy instance. Scope note: the degraded app
  only covers startup-time DB failure; a DB outage after successful startup is served by the full
  app with `/readyz` 503. After `DEGRADED_MAX_SECONDS` (default 300) the worker process exits via
  SIGTERM (daemon timer thread, probe-independent) so Gunicorn/Cloud Run respawns a fresh worker
  that retries DB init. No `--preload` is used anywhere, so respawn re-imports `wsgi` cleanly.
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
- Cancel/re-read race rule: after any remainder cancel (success, 404, or error), history is
  re-fetched and accounting uses the **second** read's `filled_qty/avg_fill_price`. Cancel 404 is
  treated as "re-query", never as success, until the vendor confirms its semantics. If the second
  read fails or the order is still open, the intent stays `unknown` + locked.
- Broker state mapping: `FILLED/PARTIAL/OPEN/SENT` → accounting path; `CANCELLED/REJECTED` with
  `filled_qty == 0` → `rejected` (lock released); `CANCELLED/REJECTED` with `filled_qty > 0` →
  accounting path (partial-post-cancel fills are real positions). Unknown raw states →
  `unknown` (lock held) + `unmapped_broker_status_total` metric (first 20 raw labels, rest `other`).
- `ALGOLAB_STATUS_MAP` (JSON env) allows alias overrides without code changes; targets are limited
  to `FILLED|PARTIAL|OPEN|CANCELLED|REJECTED` and validated at startup (fail-closed). Scope: the map
  is validated whenever set, in every broker mode, so a typo fails fast even in paper.
- Day window uses `Europe/Istanbul` and queries the previous, current, and next Istanbul day around
  the submission instant, so ±180s windows crossing midnight query both days.
- Missing history, no match, or multiple matches remains `unknown`; the symbol lock stays active and
  a critical operator alert is emitted.
- Manual **admin-only** resolution is required to release that lock, with mandatory reason,
  broker-UI confirmation, and `broker_order_id` for ack.
- Live broker startup replays persisted `pending/sent/unknown` intents (`ALGOLAB_RECONCILE_ON_STARTUP=true` default).
- Live AlgoLab refuses startup without non-SQLite `DATABASE_URL`, credentials, confirmation, and
  required endpoint configuration.
- The remainder cancel is itself a broker POST: if the cancel call itself is ambiguous (timeout),
  it is treated as "failed" and the second history read decides — the same race rule applies, so
  no separate cancel-intent ledger is needed.
- Bootstrap hash handling: `ADMIN_BOOTSTRAP_PASSWORD_HASH` is validated at boot with the exact
  acceptance set of the login verifier (scrypt/pbkdf2 via Werkzeug, bcrypt via `bcrypt.checkpw`);
  malformed values fail closed. Treat the hash as a secret (Secret Manager mount, never shell
  history); the Cloud Run yaml example value `replace_with_scrypt_or_bcrypt_hash` is an invalid
  placeholder that fails validation if deployed uncommented.

## Review-4 decisions (recorded, rollback noted)

- **D.6** remainder-cancel default `true`: approved as implemented. Rollback: set
  `ALGOLAB_RECONCILE_CANCEL_REMAINDER=false` (fills then resolve to `ack_unaccounted` + locked).
- **D.8** degraded worker-exit: approved as implemented. Rollback: raise `DEGRADED_MAX_SECONDS` or
  revert `wsgi.py` to probe-only degradation.
- **D.9** cancel-404 semantics: "re-query, never success" until the vendor confirms 404 means
  already-cancelled. No code change needed later beyond flipping `_try_cancel_remainder`.

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
- **Cloud Run deployment reality:** The GCP project currently has billing disabled and the Checked-in
  profile uses ephemeral `/tmp` SQLite. Consequently, the Cloud Run profile **can currently only run
  in paper mode**; live broker execution is blocked at boot by the F2 durability guard.
- **Gunicorn preload verification:** Gunicorn does not use `--preload` in Docker Compose, Cloud Run,
  or the Dockerfile. Worker process respawn naturally retries database initialization.

## Test traceability matrix (A.1 – A.6 & RBAC)

| Area | Implementation Focus | Test Name | File |
|---|---|---|---|
| A.1 | Double reconcile → single position change (CAS) | `test_double_reconcile_produces_single_position_change` | `tests/test_reconciled_fill.py` |
| A.1 | SELL replay after close → ack, no second PnL (exit_order_id) | `test_sell_replay_after_close_returns_ack_without_second_pnl` | `tests/test_reconciled_fill.py` |
| A.1 | CAS loser writes nothing | `test_update_conditional_loser_writes_nothing` | `tests/test_reconciled_fill.py` |
| A.1 | Reconciled SELL loss lands in position ledger | `test_reconciled_sell_loss_visible_in_position_ledger` | `tests/test_reconciled_fill.py` |
| A.1 | SELL partial quantity → `ack_unaccounted` (no reduce path) | `test_reconciled_sell_partial_quantity_is_unaccounted` | `tests/test_reconciled_fill.py` |
| A.1 | Manual resolve without broker history → `ack_unaccounted` | `test_manual_resolve_without_broker_history_is_unaccounted` | `tests/test_reconciled_fill.py` |
| A.2 | CANCELLED with fills accounted | `test_cancelled_order_with_fills_triggers_accounting` | `tests/test_reconciled_fill.py` |
| A.2 | Status map override & unmapped metric | `test_status_map_override_and_unmapped_metric` | `tests/test_reconciled_fill.py` |
| A.2 | PARTIAL 3 → cancel → second read FILLED 10 → position 10 | `test_partial_fill_cancel_then_second_read_full_fill` | `tests/test_reconciled_fill.py` |
| A.3 | Degraded worker SIGTERM timer + `/livez` 503 after expiry | `test_degraded_worker_exit_after_max_seconds` | `tests/test_reconciled_fill.py` |
| A.3 | Outage keeps liveness but fails readiness | `test_database_outage_keeps_liveness_but_fails_readiness` | `tests/test_wsgi_degraded.py` |
| A.4 | Bootstrap is one-shot via `bootstrap_state` table | `test_bootstrap_is_one_shot_via_state_table` | `tests/test_reconciled_fill.py` |
| A.4 | Hash format validated by login verifier | `test_bootstrap_hash_format_validated_by_verifier` | `tests/test_reconciled_fill.py` |
| A.4 | Pre-computed password hash format validation | `test_enforce_mode_bootstraps_first_admin` | `tests/test_rbac_bootstrap.py` |
| A.5 | Schema migration 0005 idempotency | `test_alembic_fresh_upgrade_and_downgrade` | `tests/test_alembic_migrations.py` |
| A.6 | Paper mode startup skips broker calls | `test_paper_mode_startup_reconcile_does_not_call_broker` | `tests/test_reconciled_fill.py` |
| A.7 | Background replay failure metric + critical log | `test_background_replay_failure_is_visible` | `tests/test_reconciled_fill.py` |
| RBAC | User cannot trigger scan (403) | `test_user_role_cannot_trigger_scan_in_enforce_mode` | `tests/test_scan_authz.py` |
| RBAC | Trader can trigger scan (200) | `test_trader_role_can_trigger_scan_in_enforce_mode` | `tests/test_scan_authz.py` |
| RBAC | Trader cannot resolve intent (403) | `test_manual_order_resolution_requires_admin_and_strong_confirmation` | `tests/test_scan_authz.py` |
| RBAC | Admin can resolve intent (200) | `test_manual_order_resolution_requires_admin_and_strong_confirmation` | `tests/test_scan_authz.py` |
| RBAC | Manual resolve history mismatch (409) | `test_manual_resolve_mismatch_with_broker_history_returns_409` | `tests/test_reconciled_fill.py` |
| RBAC | Rejected with fills → 409, lock kept | `test_manual_resolve_rejected_with_fills_returns_409_and_keeps_lock` | `tests/test_scan_authz.py` |
| RBAC | Rejected while open → 409 | `test_manual_resolve_rejected_while_open_returns_409` | `tests/test_scan_authz.py` |
| RBAC | Rejected without history → 503 | `test_manual_resolve_rejected_without_history_returns_503` | `tests/test_scan_authz.py` |
| RBAC | Rejected terminal zero-fill → 200, lock released | `test_manual_resolve_rejected_terminal_zero_fill_releases_lock` | `tests/test_scan_authz.py` |
| DB | `ack_unaccounted` + held `ack` keep DB symbol lock (incl. restart) | `test_ack_unaccounted_and_ack_keep_db_symbol_lock` | `tests/test_algolab_idempotency.py` |
| A.7 | Network-only replay failure never exits worker | `test_background_replay_network_error_does_not_trigger_exit` | `tests/test_reconciled_fill.py` |

## Migration execution point (D.7 answer)

`alembic upgrade head` runs at **deploy time only, never in the application worker**:
worker startup runs `Base.metadata.create_all` (idempotent safety net) plus the
Python-level legacy-schema/bootstrap steps. `alembic.ini` carries no hardcoded URL;
`env.py` resolves `DATABASE_URL` / `BIST_BOT_DATABASE_URL` / `DB_PATH` at runtime
(a hardcoded `sqlite:///bist_signals.db` that silently shadowed the environment was
removed). Deploy paths: `cloudrun/deploy.ps1` runs a gated `bist-bot-migrate` Cloud Run
Job (`alembic upgrade head`, `--wait`) when `MigrateDatabaseUrl` is non-sqlite, and skips
it for the ephemeral profile; Compose/inventory runs use an explicit
`docker compose run --rm bot alembic upgrade head` step (as in the fresh-env smoke).
The 30x2s startup-probe budget therefore only needs to cover DB connect + bootstrap +
app import. Fresh-database proof (2026-09-04): SQLite `upgrade head` + `alembic check`
exit 0 with `create_all` noop; fresh Postgres `upgrade head` + `alembic check` exit 0
after the `uq` naming-convention alignment (no migration files touched). The remaining
SQLite-only unique-constraint reflection gap is fenced by a documented dialect-scoped
`include_object` carve-out in `env.py`; PostgreSQL is the authoritative drift gate.

## Fresh-environment smoke verification (executed 2026-09-04, `-p bist-smoke`)

Isolated project with prefixed volumes/network, API on `127.0.0.1:18081`, Postgres on
`127.0.0.1:15432` (dev stack untouched), throwaway scrypt bootstrap hash. Probes run via
`docker exec` (host ports were occupied by the dev stack; HTTP surface identical).

- **Scenario 1** (empty Postgres + `RBAC_MODE=enforce` + bootstrap env): `alembic upgrade head`
  applied 0001→0005 cleanly; `/readyz` 200 (`database: ok`, paper broker, circuit CLOSED);
  1 admin seeded + `bootstrap_state=created`; login issued a JWT for the bootstrap admin.
- **Scenario 2** (fresh DB, no bootstrap env): worker failed to boot with
  `RuntimeError: No admin/trader user exists. Configure ADMIN_BOOTSTRAP_EMAIL and
  ADMIN_BOOTSTRAP_PASSWORD_HASH before enabling RBAC_MODE=enforce.` — clear fail-closed.
  (One attempt initially passed because an empty `$env:` did not propagate and repo `.env`
  values were used instead; rerun with explicit-empty override reproduced the fail-closed path.)
- **Scenario 3** (DB outage + recovery, `DEGRADED_MAX_SECONDS=20`): with Postgres stopped, a
  restarted worker logged `database_unavailable_starting_degraded_liveness`, served degraded
  `/livez` 200 + `/readyz` 503; after 20 s it logged
  `degraded_mode_lifetime_exceeded_exiting_worker`, exited via SIGTERM
  (`Worker exiting (pid: 7)`), and Gunicorn booted a second worker (`pid: 49`) — the gthread
  worker-restart path works in a real container. After Postgres returned, the next worker booted
  the full app (`/readyz` 200) and logged `admin_bootstrap_skipped_one_shot` (one-shot guard held).
- Runtime-outage note: an already-running full app answers `/livez` 200 + `/readyz` 503 during a
  DB outage; only startup-time outages take the degraded-app path (with the same probe contract).

PowerShell reproduction (throwaway secrets only):

```powershell
$env:PORT_OVERRIDE = "5005"
# Throwaway values only — never reuse or commit real secrets.
$env:JWT_SECRET_KEY = "<throwaway-jwt-secret-min-32-chars>"
$env:GRAFANA_ADMIN_PASSWORD = "<throwaway-grafana-pass>"
$env:ADMIN_BOOTSTRAP_EMAIL = "smoke-admin@test.local"
$env:ADMIN_BOOTSTRAP_PASSWORD_HASH = "scrypt:32768:8:1$smoke$dummyhashplaceholderforvalidationonly"
$env:RBAC_MODE = "enforce"

# 1. Start isolated postgres with unique project prefix
docker compose -p bist-smoke up -d postgres

# 2. Run migrations via discrete container (Decision D.7)
docker compose -p bist-smoke run --rm bot alembic upgrade head

# 3. Start API container and verify readiness
docker compose -p bist-smoke up -d bot
curl.exe -fsS http://127.0.0.1:5000/readyz

# 4. Outage degradation test: stop postgres, verify liveness=200 degraded, readiness=503
docker compose -p bist-smoke stop postgres
curl.exe -fsS http://127.0.0.1:5000/livez
# Cleanup smoke project
docker compose -p bist-smoke down -v
```

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
- Patch-set quarantine (2026-09-04): `gitleaks detect --no-git --source patches` found 9
  candidates across the retired `security-phase1-*` / `full-18` / `full-24` sets — all verified as
  test dummies (`test_secret_key_...`, also present in the committed tree and allowlisted by
  `.gitleaks.toml`) or an already-replaced docs placeholder. No patch file contained the leaked
  `opencode.json` key (the `16d5fbc` deletion diff was never part of any patch dir). All retired
  sets were deleted from disk; the handoff artifact is a freshly generated, rescanned clean series
  (`patches/security-phase1-clean/`, 0 findings with repo config).
- A disposable rewrite mirror and replace-text helper used during verification were deleted.
  The labeled pre-rewrite bundle (`%TEMP%/opencode/bist-bot-before-rewrite.bundle`, verified)
  is retained as the sole recovery copy until the incident closes, then must be deleted.
- Rotation, provider usage/billing review, fork notification, history rewrite, GitHub cache cleanup,
  and collaborator reclone remain owner actions. No rewrite or force-push was performed in this run.

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
