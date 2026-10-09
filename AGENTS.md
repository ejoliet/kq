<!-- AGENTS.md — agent guidance for kq
     Last reviewed: 2026-10-08  Owner: ejoliet
     AIDEV-NOTE: keep ≤ 200 lines. Spec lives in README.md; this file holds only rules the spec does not make obvious. -->

# kq

Session kernel CLI for coding agents: captures large stdout into versioned Parquet artifacts in a per-session DuckDB store. Full contract in `README.md`.

## Project invariants (do not violate)

1. **`kq run` never loses output and always mirrors the wrapped exit code.** On any internal failure (lock, store, detection), print the raw stdout and exit with the command's code. Warnings go to stderr.
   Blast: the agent acts on missing data or treats a failed command as success.
2. **Nothing reaches disk unscrubbed.** Parquet files, `kq.events`, `kq.artifacts.producer_text`, and `view.html` all receive scrubbed content only. Scrub before detection, not after.
   Blast: credentials from `aws`/`gh` output end up in session dirs and shared `view.html` files.
3. **`kq q` and `kq commit` accept a single SELECT only.** Check with `json_serialize_sql` (`error: true` → reject) and run `q` on a `read_only=True` connection.
   Blast: the agent mutates evidence; provenance and staleness become wrong.
4. **Artifact versions are immutable.** A change writes `<handle>.v<N+1>.parquet` and flips `is_current`; never overwrite a Parquet file or update a non-current row.
   Blast: edges point at data that changed under them; `kq stale` lies.
5. **kq never re-runs a captured command.** Staleness is a flag, not a trigger. No "refresh" feature.
   Blast: side-effectful commands (`aws`, `kubectl apply`, deploy scripts) run twice.
6. **Cold start under 300 ms for `index`, `q`, and small `run`.** No module-level import of `opentelemetry`; import `otel_export` only when `KQ_OTLP_ENDPOINT` is set. No new runtime dependency besides `duckdb` without a reason in the PR.
   Blast: agents call kq dozens of times per session; slow calls make them stop using it, and the eval fails.
7. **OTel attribute names appear only in `otel_map.py`.** The GenAI conventions are Development status and can rename attributes. Keep `SEMCONV_COMMIT` pinned there.
   Blast: a rename forces edits across modules and silently breaks exported traces.
8. **Type detection follows the README table exactly.** DuckDB's CSV sniffer reports delimiter `,` for plain text; never use "sniff succeeded" as proof of CSV.
   Blast: every log becomes a one-column "table" and summaries become useless.
9. **Handle-line format is a contract.** `<handle>  <kind>  <shape>  <summary>`, two spaces between fields. The eval and the skill parse it.
   Blast: capture-rate metrics break; agents mis-read handles.
10. **Nothing kq prints may exceed the token budget.** `q` spills to a `q###` artifact; `describe`, error hints, `index`, and `stale` truncate. Error hints list column names and types only, never values.
   Blast: kq leaks the same token cost it exists to remove.
11. **Dedup compares hashes of scrubbed bytes and only suppresses byte-identical output.** Any difference, however small, is a new version.
   Blast: the agent is told "unchanged" about data that changed and reports stale conclusions.
12. **Envelope unwrap is one level, one key, and only when that key is the object's sole array of objects.** Record `envelope_key`; keep other top-level scalars in the summary.
   Blast: guessing the wrong array silently drops data from the table.
13. **No literal secret-shaped strings in the repo**, including tests, fixtures, and docs. Build fake tokens at runtime (`tests/secrets.py`).
   Blast: GitHub secret scanning can block the push; real-looking tokens in a public repo get reported and erode trust in a tool that promises scrubbing.

> If an instruction below conflicts with an invariant, the invariant wins.

## Project skills (`.claude/skills/`)

| Skill | Invoked by | Purpose |
|---|---|---|
| `kq-phase` | You only: `/kq-phase 2` | Implement one build phase, test, stop, print your checks |
| `kq-fixtures` | Claude, when touching `tests/**` | Fixture shapes, fake-secret and offline rules |
| `verify` | Claude, before each commit (Claude Code v2.1.286+) | ruff, pytest, staged-diff secret scan. Replaces the bundled `/verify` in this repo |
| `kq` (dogfood) | Claude, after you enable it | The product skill, used while building kq. Enable only after Phase 2 passes (command below) |

Keep these short and pointing to README/AGENTS; do not restate rules from either file.

## Workflow

- Follow the build order in `README.md`. Finish a phase's tests before starting the next.
- Run `uv run pytest -q` and `uv run ruff check .` before declaring a phase done.
- Tests are offline. Wrapped commands in tests are `python -c` scripts printing fixtures from `tests/fixtures/`.
- When a CLI flag, env var, schema column, or error code changes, update the matching table in `README.md` and, if user-facing, `skill/kq/SKILL.md`.
- Record agent mistakes as dated lines under a `## Recently burned` section in this file, newest first, max 5.

## Out of scope for the agent

Emmanuel runs these himself. Do not attempt them; stop and list what is ready to check.

- Pushing, opening PRs, tagging releases.
- Opening `view.html` in a browser or judging how it looks.
- Installing Docker, Jaeger, or skills-ref.
- Running the evaluation in `docs/eval.md` (it uses paid model calls).

## Verification commands per phase (Emmanuel)

| Phase | Command | Expect |
|---|---|---|
| 0 | `uv run kq --version` | version string |
| 1 | `uv run pytest -q tests/test_store.py tests/test_events.py` | pass |
| 2 | `uv run kq run -- python -c "print('x'*20000)"` then `uv run kq index` | one handle line; artifact listed |
| 2 | `uv run kq run -- python -c "import sys; sys.exit(3)"; echo $?` | `3` |
| 2 | Run the same `uv run kq run -- python -c "print('x'*20000)"` twice | second prints `unchanged since r00N v1` |
| 3 | `uv run kq q "delete from r001"; echo $?` | `E_SQL_REJECTED`, `4` |
| 3 | `uv run kq q "select nosuchcol from r001"` | error followed by `columns of r001: …` |
| 3 | `uv run kq describe r001` | one row per column |
| 3 | `uv run kq run --as src -- python -c "print('a,b\n1,2\n'*3000)"` twice around a `kq commit d "select * from src"`, then `uv run kq stale` | `d v1 ← src v1 (now v2)` |
| 4 | `for i in 1 2 3; do /usr/bin/time -p uv run kq index >/dev/null; done` | real < 0.3 s after first run (`uv run` adds overhead; re-check with installed `kq`) |
| 5 | `uv run kq view \| xargs open` (macOS) | page loads, SQL box returns rows |
| 6 | `docker run --rm -d -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one` then `KQ_OTLP_ENDPOINT=http://localhost:4318 uv run --extra otel kq run -- cat tests/fixtures/pods.json` | span `execute_tool kq.run` at http://localhost:16686 |
| 7 | `skills-ref validate ./skill/kq` | valid |
| After 2 | Dogfood: `uv tool install --editable . && ln -s ../../skill/kq .claude/skills/kq` | `kq --version` works; `/skills` lists `kq` |
| Any | `claude plugin validate .claude/skills` (Claude Code v2.1.233+) | all project skills parse |
| Release | `uvx --from git+https://github.com/ejoliet/kq kq --version` | version string |

## Conventions

- Anchor comments use `AIDEV-NOTE:`, `AIDEV-TODO:`, `AIDEV-QUESTION:`. Preserve them when refactoring.
- No comments that restate code.
- Error codes and exit codes come only from the `README.md` error table.

## Stack

- Lang: Python 3.11+ · Pkg: uv (src layout, `kq = "kq.cli:main"`) · Test: pytest · Lint: ruff
- Engine: duckdb 1.5.x · Viewer: `@duckdb/duckdb-wasm@1.32.0` via jsDelivr · Optional: opentelemetry-sdk + OTLP/HTTP exporter 1.45.x
