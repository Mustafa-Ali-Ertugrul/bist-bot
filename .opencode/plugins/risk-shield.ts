export default function riskShieldPlugin() {
  const blockedPatterns = [
    /rm\s+-rf\s+\//,
    /git\s+push\s+--force/,
    /docker\s+system\s+prune\s+-a/,
    /chmod\s+-R\s+777/,
    /gcloud\s+run\s+deploy/,
    /alembic\s+upgrade\s+head/,
    /psql.*drop\s+table/i
  ];

  return {
    name: "risk-shield",
    hooks: {
      "tool.execute.before": async (event: any) => {
        if (event.tool !== "bash") return;

        const cmd = String(event.input ?? "");
        for (const pattern of blockedPatterns) {
          if (pattern.test(cmd)) {
            throw new Error(
              `Blocked risky command by risk-shield: ${cmd}`
            );
          }
        }
      }
    }
  };
}
