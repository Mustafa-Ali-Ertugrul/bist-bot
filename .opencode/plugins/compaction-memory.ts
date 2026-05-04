import fs from "node:fs";
import path from "node:path";

export default function compactionMemoryPlugin() {
  return {
    name: "compaction-memory",
    hooks: {
      "session.compact.before": async () => {
        const memoPath = path.join(process.cwd(), ".opencode", "session-memo.md");
        const memo = [
          "# Session Memory",
          "- Active problem:",
          "- Files currently being modified:",
          "- Confirmed root cause(s):",
          "- Hypotheses not yet confirmed:",
          "- Tests already run:",
          "- Remaining risks:",
          "- Next recommended step:"
        ].join("\n");
        fs.writeFileSync(memoPath, memo);
      }
    }
  };
}
