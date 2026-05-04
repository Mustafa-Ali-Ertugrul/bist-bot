# Eval Task: Market Data Audit

## Scenario
The user reports that scan results are inconsistent: 108 stocks were fetched, but only a few appear on the dashboard. There are suspected gaps in OHLCV data and potential stale history issues with yfinance.

## Objectives
1.  **Trace the Pipeline:** Identify the code path from provider fetch -> data validation -> scanner processing -> database persistence.
2.  **Identify Vulnerabilities:** Find where data might be silently dropped or where incomplete OHLCV rows might cause the scanner to skip a stock.
3.  **Root Cause Hypothesis:** Provide a grounded hypothesis (e.g., "Scanner requires 50 bars of history, but provider only returns 45 without warning").
4.  **Minimal Fix:** Propose a change to ensure visibility (e.g., add logging for skipped stocks or lower the threshold).

## Expected Files to Inspect
- `src/bist_bot/providers/`
- `src/bist_bot/scanner.py`
- `src/bist_bot/db/`

## Success Criteria
- Agent identifies the exact filtering logic in `scanner.py`.
- Agent notes the lack of error reporting when a stock is skipped due to data gaps.
- Agent proposes a fix involving improved logging or a more robust fallback.
