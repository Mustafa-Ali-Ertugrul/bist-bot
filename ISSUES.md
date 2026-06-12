# Issue Backlog

## Dashboard Signal Semantics Follow-ups

### Notifier HOLD semantics
- Source: PR #52 known follow-up.
- Problem: `notifier.py` still classifies positive, negative, and zero scores directly with `score > 0`, `score < 0`, and `score == 0`.
- Goal: Align notifier copy with `SignalType` semantics so HOLD/BEKLE messages are not presented as actionable buy/sell ideas.
- Validation: Add targeted notifier tests covering BUY, STRONG_BUY, HOLD/BEKLE, and SELL-style outputs.

### Consume scan_stats outside overview
- Source: PR #52 known follow-up.
- Problem: `scan_stats` is propagated through the runtime scan path, but `signals_page` and `portfolio_page` do not consume it yet.
- Goal: Decide whether these pages should show generated/actionable/hold-watch scan counts and add the UI only where it improves clarity.
- Validation: Add focused Streamlit rendering tests for pages that consume `scan_stats`.

### Align scanned and scanned_count naming
- Source: PR #52 known follow-up.
- Problem: Scan payload naming mixes `scanned` and `scanned_count`, which makes API/UI contracts harder to reason about.
- Goal: Choose one canonical field name and keep backward-compatible handling for existing payloads.
- Validation: Add runtime/API tests proving old and new payloads are handled safely.
