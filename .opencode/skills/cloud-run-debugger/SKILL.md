---
name: cloud-run-debugger
description: Diagnose Cloud Run issues involving startup, session, routing, env vars, and timeouts.
---

Use this skill when:
- login works locally but not in Cloud Run
- requests timeout in production
- UI/API behave inconsistently after deploy
- revisions behave differently

Check:
- cold start sensitivity
- request timeouts
- container port assumptions
- sticky session assumptions
- env var drift
- service-to-service URL mismatches
- auth/session storage model
- startup/readiness expectations

Output:
- symptom
- probable cause
- evidence path
- smallest safe remediation
- deploy verification
