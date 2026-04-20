# Contributing

## Branching
- Use `master` as the stable branch.
- Create a feature branch for any non-trivial change:
  - new modules
  - protocol or config changes
  - refactors
  - behavior changes
  - grouped test updates
- Keep unrelated work out of the same branch.

## Commit Discipline
- Keep each commit focused on one reason to change.
- Prefer small, reviewable commits.
- Do not mix deploy, feature, refactor, and test-fix work in one commit.
- A bug fix and its matching test update can be committed together.

## What Can Go Directly to Master
- Very small, low-risk fixes
- Clearly scoped docs updates
- Safe single-purpose changes with local verification

## What Should Use a Branch
- New features
- Execution or trading logic changes
- Config or settings changes
- Docker or CI changes
- Refactors
- Multi-file edits with behavioral impact

## Before You Commit
Run the checks that match your change. At minimum:

```bash
git diff --staged
git status
```

Common validations:

```bash
python -m pytest tests/ -v --tb=short
ruff check .
python -m compileall config config_store.py db state ui data_fetcher.py strategy.py risk_manager.py streamlit_app.py
```

## Before You Push
- Confirm only intended files are staged.
- Make sure the working tree is clean or that remaining changes are intentional.
- Review the final staged diff one last time.

## If CI Fails
- Identify the failing step first.
- Reproduce locally if possible.
- Fix the smallest possible scope.
- Push the fix as a separate commit.
- Do not bundle speculative cleanup with the CI fix.

## Working Tree Hygiene
- Do not leave partial feature work on `master`.
- If work is incomplete, move it to a branch or stash it.
- Keep `master` deployable and CI-green.

## Recommended Workflow
1. Create a branch
2. Make one focused change
3. Run relevant checks
4. Commit with a clear message
5. Push and watch CI
6. Merge only after CI passes
