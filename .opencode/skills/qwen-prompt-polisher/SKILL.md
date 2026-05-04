---
name: qwen-prompt-polisher
description: Rewrite prompts so Qwen follows them more reliably and with less drift.
---

Use this skill when:
- Qwen over-explains
- Qwen edits too broadly
- Qwen misses constraints
- Qwen confuses planning vs implementation

Prompt rules:
- use explicit role
- define allowed actions
- define forbidden actions
- require output schema
- minimize ambiguity
- separate analysis from execution
- request file-path grounded reasoning

Output:
- original weakness
- improved prompt
- why the rewrite should work better
