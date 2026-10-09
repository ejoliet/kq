---
name: verify
description: Pre-commit check for kq. Runs lint, format, the offline test suite, and a staged-diff scan for secret-shaped literals.
allowed-tools: Bash(uv run ruff *) Bash(uv run pytest *) Bash(git diff --cached *)
---

# Verify kq before committing

Run in order. Stop at the first failure, fix it, and run all steps again.

1. `uv run ruff check .`
2. `uv run ruff format --check .`
3. `uv run pytest -q`
4. Secret-literal scan of the staged diff. Expected output: nothing.
   ```bash
   git diff --cached -U0 | grep -E '^\+' | grep -nE '(AKIA|ASIA)[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}|xox[abprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.' || true
   ```
   Any match is a blocker: replace the literal with a runtime-built value (see `kq-fixtures`).

Report pass or fail per step in one line each. Do not commit if any step fails.
