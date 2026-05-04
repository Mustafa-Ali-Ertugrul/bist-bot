# Eval Task: Cloud Run Debug

## Scenario
Production users report intermittent 500 errors on the scan endpoint and frequent logouts/session loss. The UI sometimes times out while waiting for scan results, and background scans occasionally appear "stuck" in progress.

## Objectives
1.  **Analyze Timeout Chain:** Inspect timeout settings across UI (Streamlit), API (Flask/FastAPI), and Cloud Run configuration.
2.  **Session & Auth State:** Evaluate how authentication state is persisted. Check for instance-local state vs. shared persistence (Redis/DB) and the impact of Cloud Run's stateless nature.
3.  **Scan Lifecycle:** Investigate how background tasks are handled. Check for potential blocking calls, lack of timeouts on futures, or zombie processes.
4.  **Infrastructure Evidence:** Identify if the issue is application-level or caused by Cloud Run constraints (e.g., cold starts, lack of session affinity).

## Expected Files to Inspect
- `cloudrun/` (Dockerfile, service.yaml if present)
- `.github/workflows/`
- `src/bist_bot/ui/runtime*.py`
- `src/bist_bot/auth/`
- `src/bist_bot/scheduler.py` or `scanner.py` for task handling.

## Success Criteria
- Agent identifies the mismatch between UI request timeouts and Cloud Run request timeouts.
- Agent notes the risk of using instance-local memory for sessions in a multi-instance Cloud Run setup.
- Agent distinguishes between confirmed code bugs and suspected infra behavior (e.g., cold starts).
- Agent proposes a minimal fix focused on visibility or robust timeout handling.
