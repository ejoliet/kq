# Implementation notes

One line per non-obvious decision. Newest last.

- 2026-10-09 Phase 0: hatchling + src layout, `dependency-groups.dev` for pytest/ruff so the runtime dependency set stays `duckdb` only (invariant 6).
- 2026-10-09 DEVIATION: session DB file is `session.duckdb`, not `kq.duckdb`. DuckDB names the catalog after the file, so a `kq` catalog makes every `kq.events` reference raise "Ambiguous reference to catalog or schema". README updated. Alternative rejected: fully qualifying every query as `kq.kq.events`, which would leak into the agent-facing SQL contract.
- 2026-10-09 Timestamps stay in SQL: DuckDB needs `pytz` to hand a TIMESTAMPTZ to Python, and that would be a new runtime dependency. `index` selects `epoch(created_at)`; tests cast to VARCHAR.
- 2026-10-09 Scrub patterns are bytes, not str: non-UTF-8 captures must be scrubbed before any decode, and the decode to replacement characters happens later, only for the text rule.
- 2026-10-09 `kq_secret` value patterns exclude `[REDACTED` so the generic key=value rule does not re-redact a token the specific rule already replaced.
- 2026-10-09 Text artifacts are read with `read_csv` using `\x1f`/`\x1e` as delimiter and quote, after rewriting the capture as valid UTF-8. Alternative rejected: inserting lines from Python, which is far slower on large logs.
- 2026-10-09 DEVIATION: `read_json(maximum_object_size=...)` is capped at 256 MB, not `KQ_MAX_BYTES` (2 GB). DuckDB allocates that buffer up front and fails with "IO Error: Invalid argument" at 2 GB.
- 2026-10-09 NDJSON detection parses the first 1000 lines and prefix-checks the rest; full parsing of a multi-GB capture costs more than the rule is worth.
- 2026-10-09 DEVIATION: capture orchestration (`cmd_run`, `_store`) lives in `capture.py`, not `cli.py`; the README file map gives `cli.py` only "parse args, dispatch, map errors to exit codes".
- 2026-10-09 `kq index` was implemented in phase 2 (not phase 4) because the AGENTS.md phase-2 verification row uses it. Only the listing exists; `--all` currently lifts the 30-row cap but superseded-unnamed-artifact hiding and `stale?` wait for phases 3–4.
