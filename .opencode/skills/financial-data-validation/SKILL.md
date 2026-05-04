---
name: financial-data-validation
description: Validate financial market data quality, freshness, continuity, and provider behavior.
---

Use this skill when:
- scan results look too sparse
- chart data has gaps
- provider reliability is in doubt
- derived indicators may be using incomplete inputs

Check:
- required columns
- monotonic dates
- stale dates
- missing intervals
- duplicate rows
- timezone assumptions
- fallback behavior
- symbol formatting

Output:
- data quality findings
- likely impact on signals
- code hotspots
- concrete remediation
- recommended tests
