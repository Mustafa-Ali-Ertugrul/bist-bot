Inspect the current diff and write the highest-value targeted tests.

Rules:
- Prefer tests that verify behavior changed by the diff.
- Avoid brittle snapshots unless necessary.
- Cover regression risk before happy path expansion.
- Explain why each test matters.

Use agent: test-runner
