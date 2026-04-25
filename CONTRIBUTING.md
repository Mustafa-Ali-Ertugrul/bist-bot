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

## Local Development Setup

```bash
# Clone and create venv
git clone <repo-url> bist_bot && cd bist_bot
python -m venv .venv && source .venv/bin/activate

# Install runtime + dev deps
pip install -r requirements.txt -r dev-requirements.txt

# Install pre-commit hooks (one-time)
pre-commit install

# Run all checks manually
pre-commit run --all-files
```

After `pre-commit install`, every `git commit` will automatically run:
- `ruff check --fix` and `ruff format`
- trailing whitespace, EOF, YAML/TOML syntax checks
- `mypy` on `strategy/` and `risk/` modules

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

```bash
# Format + lint (auto-fixes safe issues)
ruff check . --fix
ruff format .

# Run tests with coverage
export PYTHONPATH=src
pytest tests/ -v --cov=src/bist_bot --cov-report=term-missing

# Type check (strategy + risk modules)
mypy src/bist_bot/strategy src/bist_bot/risk --ignore-missing-imports

# Final review before staging
git diff --staged
git status
```

## Before You Push
- Confirm only intended files are staged.
- Make sure the working tree is clean or that remaining changes are intentional.
- Review the final staged diff one last time.

## CI Pipeline

GitHub Actions runs on every push and PR (`master` and `main` branches):

1. **lint** — `ruff check`, `ruff format --check`, `mypy`, `compileall`
2. **test** — `pytest` on Python 3.11 + 3.12 with coverage (≥60% required)
3. **security** — `pip-audit` (CVE scan) + `bandit` (static analysis)

Coverage report is uploaded as artifact on the 3.11 run.

## If CI Fails
- Identify the failing step first.
- Reproduce locally:
  - Lint: `ruff check . --output-format=github`
  - Tests: `pytest tests/ -v --cov-fail-under=60`
  - Security: `pip-audit --requirement requirements.txt`
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
3. Run relevant checks (`pre-commit run --all-files`, `pytest`)
4. Commit with a clear message
5. Push and watch CI
6. Merge only after CI passes
