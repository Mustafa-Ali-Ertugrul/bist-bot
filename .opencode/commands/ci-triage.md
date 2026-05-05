Analyze and triage CI/CD pipeline failures.

Workflow:
1. Identify the failing stage and job.
2. Extract the relevant error log snippet.
3. Classify the failure: logic / environment / flakiness / config.
4. Propose the smallest fix to restore green status.

Use agent: test-runner
