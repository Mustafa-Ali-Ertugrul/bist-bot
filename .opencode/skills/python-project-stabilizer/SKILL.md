---
name: python-project-stabilizer
description: Stabilize Python applications with minimal-risk fixes and targeted validation.
---

Use this skill when:
- a Python service is flaky
- production behavior differs from local
- a bug likely involves config/runtime/test mismatch

Do not use when:
- the task is purely architectural
- the request is only for high-level brainstorming

Checklist:
1. Identify failing entrypoint.
2. Inspect config loading path.
3. Inspect runtime assumptions.
4. Prefer minimal diff.
5. Run targeted checks first.
6. State residual risk.

Focus areas:
- environment loading
- retries/timeouts
- thread/process assumptions
- serialization boundaries
- test coverage gaps

Output:
- root cause
- smallest safe fix
- validation commands
- follow-up hardening
