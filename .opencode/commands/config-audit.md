Audit project configuration files for inconsistencies, security risks, and deployment mismatches.

Check:
- .env vs .env.example
- hardcoded secrets
- timeout/retry logic
- provider fallback settings
- Cloud Run resource limits
- development vs production divergence

Output:
- findings
- risks
- remediation steps

Use agent: reviewer
