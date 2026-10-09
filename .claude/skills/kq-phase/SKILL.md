---
name: kq-phase
description: Implement one kq build phase from README.md, test it, then stop for Emmanuel's checks.
disable-model-invocation: true
argument-hint: "[phase-number]"
arguments: [phase]
allowed-tools: Bash(uv run pytest *) Bash(uv run ruff *)
---

# Build phase $phase

## Current state

!`git status --short`
!`git log --oneline -5 || true`

## Steps

1. Read the `README.md` build-order row for phase $phase, plus only the README sections that row depends on. Read the invariants in `AGENTS.md`.
2. Run `uv run pytest -q`. If earlier phases fail, stop and report; do not start phase $phase.
3. Post a plan of 3–6 lines: files to create or change, tests to add. Then proceed.
4. Write the phase's tests first, from its "Done when" column and the matching acceptance criteria. Follow the `kq-fixtures` skill for any fixture.
5. Implement. Keep every invariant in `AGENTS.md`. Add `AIDEV-NOTE:` only where the code would otherwise look wrong.
6. Run the phase's tests, then `uv run pytest -q`, `uv run ruff check .`, and `uv run ruff format --check .`. Fix until all pass.
7. If a CLI flag, env var, schema column, error code, or handle-line field changed, update the matching table in `README.md`, and `skill/kq/SKILL.md` if user-facing.

## Stop and report

Do not commit, push, or start the next phase. Reply with:

- Files changed, one line each.
- Test and lint results (counts only).
- Any deviation from `README.md`, with the reason.
- Open questions, if any.
- The verification rows for phase $phase from `AGENTS.md`, copied verbatim, for Emmanuel to run.
- After phase 2 passes: a reminder that the dogfood step in `AGENTS.md` is now available.
