# Issue Backlog

## Dashboard Signal Semantics Follow-ups (PR #52 — resolved 2026-09-03)

### Notifier HOLD semantics — RESOLVED
- Source: PR #52 known follow-up.
- Problem (was): `notifier.py` still classifies positive, negative, and zero scores directly with `score > 0`, `score < 0`, and `score == 0`.
- Resolution: `notifier.py` no longer contains any direct score-sign comparison;
  all labels go through `categorize_signal()` / `SignalCategory`
  (`_build_diagnosis_block`, `_build_signal_message`, scan summary builders).
  HOLD/BEKLE messages are never presented as actionable ideas.
- Validation: `tests/test_notification_dispatch.py` (RADAR/İZLE labels),
  `tests/test_signal_categorization.py` (category matrix incl. HOLD edge cases),
  `tests/test_scanner.py::TestHoldSignalPersistence`.

### Consume scan_stats outside overview — RESOLVED BY DECISION
- Source: PR #52 known follow-up.
- Decision: `overview_page` and `scan_detail_page` consume `scan_stats` /
  `latest_scan` (session + API, back-compat both locations). `signals_page`
  derives counts from loaded `all_data` (correct for its filtered view).
  `portfolio_page` intentionally shows no scan counts — it is holdings-focused;
  scan coverage lives on overview/scan-detail. No UI change needed.
- Validation: `tests/test_ui_layer_integration.py`,
  `tests/test_runtime_scan.py`.

### Align scanned and scanned_count naming — RESOLVED
- Source: PR #52 known follow-up.
- Resolution: canonical field is `scanned`; `scanned_count` is kept as a
  read-only alias in the same payload (`src/bist_bot/dashboard.py`,
  `api_scan_completed` log uses `scanned_count=` for continuity).
  New consumers must read `scanned`.
- Validation: `tests/test_dashboard_cache.py` (`payload["scanned"]`),
  `tests/test_integration_flows.py`, `tests/test_ui_layer_integration.py`.
