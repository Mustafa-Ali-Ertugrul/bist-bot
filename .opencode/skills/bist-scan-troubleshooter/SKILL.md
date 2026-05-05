---
name: bist-scan-troubleshooter
description: Diagnose BIST scan issues across fetch, filter, scoring, persistence, and UI display.
---

Use this skill when:
- scans hang
- scanned count and displayed count diverge
- signals disappear after successful fetch
- background scan behaves differently from UI scan

Investigate in order:
1. provider fetch path
2. scan timeout/future path
3. filtering stages
4. scoring thresholds
5. persistence logic
6. API payload
7. UI rendering assumptions

Output:
- exact failing stage
- likely cause
- minimal safe fix
- how to prove it
