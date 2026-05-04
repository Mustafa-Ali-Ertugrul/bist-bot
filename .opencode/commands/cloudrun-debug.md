Investigate Cloud Run production issues in bist-bot.

Focus areas:
- login/session persistence across reruns and instances
- API request timeout mismatches between UI and API
- scan endpoint returning 500 or staying in progress
- background scan worker blocking or hanging
- env var drift across revisions
- service URL / auth / state assumptions between UI and API

Rules:
- inspect relevant files before proposing changes
- distinguish confirmed evidence from hypotheses
- prefer the smallest safe fix
- include validation and deploy verification steps

Output:
1. confirmed symptoms
2. likely root causes ranked
3. affected files
4. minimal safe fix
5. validation steps
6. deployment verification checklist

Use agent: architect
