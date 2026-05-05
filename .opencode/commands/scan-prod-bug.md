Analyze a production issue in this repository.

Steps:
1. Identify the exact failing surface area.
2. Trace likely code paths.
3. List the top 3 root-cause hypotheses.
4. Rank them by probability.
5. Propose the smallest safe fix.
6. List validation commands.
7. If logs/config/deploy are relevant, say exactly where to inspect.

Constraints:
- Do not make speculative claims without labeling them as hypotheses.
- Prefer concrete file paths and functions.
- Keep proposed changes minimal.

Use agent: plan
