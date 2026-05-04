---
name: test-failure-triage
description: Triage failing tests with a minimal-fix mindset.
---

Use this skill when:
- CI fails
- new tests are flaky
- production fix broke existing behavior

Approach:
- classify failure: logic / environment / brittle expectation / ordering / timing
- isolate the smallest reproducer
- decide whether code or test is wrong
- propose the smallest correct change

Output:
- failure class
- root cause
- fix recommendation
- regression risk
