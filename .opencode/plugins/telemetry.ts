import fs from "node:fs";
import path from "node:path";

const logPath = path.join(process.cwd(), ".opencode", "telemetry.log");

function write(entry: Record<string, unknown>) {
  fs.appendFileSync(logPath, JSON.stringify(entry) + "\n");
}

export default function telemetryPlugin() {
  return {
    name: "telemetry",
    hooks: {
      "session.created": async (event: any) => {
        write({ type: "session.created", ts: Date.now(), event });
      },
      "session.error": async (event: any) => {
        write({ type: "session.error", ts: Date.now(), event });
      },
      "tool.execute.after": async (event: any) => {
        write({
          type: "tool.execute.after",
          ts: Date.now(),
          tool: event.tool,
          duration_ms: event.duration_ms,
          success: event.success
        });
      }
    }
  };
}
