# Credential Rotation and History Rewrite Runbook

## Confirmed incident scope

- Public repository: `Mustafa-Ali-Ertugrul/bist-bot`
- Public fork count observed on 2026-09-04: 1
- Gitleaks history finding: commit `6d0fa86e194708840f26d6a91447d0813a25c184`,
  `opencode.json:26`, rule `generic-api-key`
- The key value was never printed or copied during remediation.
- `opencode.json` has been removed from Git tracking and excluded by both `.gitignore` and
  `.dockerignore`; the user's local file remains intact.
- Working-tree scan found four redacted findings in the ignored local `.env`. These must remain
  local and must not be added to Git or container contexts.
- Artifact Registry enumeration is blocked because billing is disabled on the configured GCP
  project. Existing image inventory and deletion cannot yet be completed. Plan the deletion step
  **before** re-enabling billing/redeploying: enable billing, list and delete old image revisions
  that may contain the tracked `opencode.json`, then deploy fresh images.

## Stage 1 — Provider-side containment (owner action, do first)

1. Identify the provider for the historical key locally. Do not paste the old or new key into an
   issue, PR, terminal transcript, or chat.
2. Revoke the old key at the provider.
3. Review provider usage/billing/audit logs from 2026-06-08 onward for unknown activity.
4. Create a replacement with minimum scopes and an expiry where supported.
5. Store the replacement only in the appropriate local secret store or CI/Cloud Secret Manager.
6. Verify the old credential is rejected before proceeding.

## Stage 2 — Preserve current work before rewriting history

This repository has unrelated local/untracked research artifacts. Do not run `reset`, `clean`, or
`filter-repo` in the current worktree. Security changes are committed separately and backed up with
`git format-patch` before rewriting.

## Stage 3 — Coordinated rewrite window

Prerequisites:

- credential rotation confirmed;
- all maintainers notified and pushes temporarily frozen;
- open PRs and protected branch rules reviewed;
- mirror backup stored offline;
- force-push explicitly approved.

Use a new disposable mirror clone, not the current worktree:

```bash
git clone --mirror https://github.com/Mustafa-Ali-Ertugrul/bist-bot.git bist-bot-rewrite.git
cd bist-bot-rewrite.git
git bundle create ../bist-bot-before-rewrite.bundle --all
```

Preferred rewrite keeps `opencode.json` out of every historical ref:

```bash
git filter-repo --path opencode.json --invert-paths --force
```

Then scan the rewritten mirror before any push:

```bash
gitleaks detect --source . --redact --log-opts="--all"
```

Only after review of the rewritten refs:

```bash
git push --force --mirror origin
```

The force-push command is intentionally not executed by this remediation run.

## Stage 4 — After the rewrite

1. Ask GitHub Support to purge cached/orphaned objects for the exposed commit.
2. Notify the known fork owner that history contained a revoked credential. Note that a fork keeps
   its own copy of history, so a rewrite does not clean the fork; removal there needs a personal
   request to the fork owner (DMCA/takedown only as a last resort, maintainer decision).
3. Require collaborators to delete old clones or reclone; old objects still contain the key.
4. Reapply the generated security format patches onto the rewritten default branch.
5. Re-run history and working-tree Gitleaks scans.
6. Rebuild and redeploy images only after Artifact Registry inventory is available.
7. Delete old registry image revisions that may contain the tracked `opencode.json`.

## Rollback

The pre-rewrite Git bundle is the recovery source for repository history. It contains the revoked
secret and must therefore be encrypted, access-restricted, and deleted when the incident closes.
