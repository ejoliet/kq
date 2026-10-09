# kq

> A session kernel for coding agents: large command outputs become named, queryable DuckDB artifacts instead of raw text in the model's context.

## Purpose

**Problem.** Coding agents paste large command output (logs, JSON inventories, catalogs, test runs) into their context. That costs tokens, crowds out reasoning, and is lost after context compaction.

**Solution.** `kq` wraps shell commands. Small output passes through unchanged. Large output is stored as a Parquet-backed artifact; the agent gets a handle, shape, and 1-line summary, then queries it with SQL. Derived results are committed with provenance, stale results are flagged, and a human can open the whole session as one static HTML page.

**Who benefits.** Anyone running Claude Code, Codex, OpenCode, or another skills-capable agent with a shell, on data-heavy work.

**Inspiration.** marimo pair: the agent works against a live kernel, inspects state in a scratchpad, and makes durable changes through an API. `kq` applies that model to a shell session, with DuckDB as the kernel.

## Architecture

- **Capture.** `kq run -- <cmd>` spools the command's stdout to a temp file, mirrors its exit code, and measures size.
- **Threshold.** Below `KQ_THRESHOLD_TOKENS` (estimated as `bytes / 4`), stdout is printed unchanged and nothing is stored.
- **Store.** Above it: scrub secrets → hash → detect type (unwrapping JSON envelopes) → write one Parquet file → register a versioned artifact → create a DuckDB view named after the handle → print the handle line.
- **Dedup.** If the scrubbed output hash equals the current version of the target handle (`--as`) or of any artifact from the same command in this session, no new version is written; kq prints `unchanged since <handle>`.
- **Query budget.** `kq q` results above the threshold are stored as a `q###` artifact (with edges) and returned as a handle line, never printed in full.
- **Kernel.** One DuckDB file per session. Metadata tables live in schema `kq`; artifact views live in `main`, so `kq q "select … from r003"` works.
- **Events.** Every command appends one row to `kq.events`, shaped as an OpenTelemetry span (session = trace, call = span). Optional OTLP export.
- **Provenance.** `kq commit` parses the SQL with DuckDB's own parser, records edges to the exact versions it read, and materialises a new artifact.
- **Staleness.** An artifact is stale when any upstream it was derived from has a newer version, transitively. Flag only; nothing re-runs.
- **View.** `kq view` writes one self-contained HTML file: DuckDB-WASM from a CDN plus the session's Parquet files embedded as base64.

```text
agent shell ──kq run──▶ spool ─┬─ small ─▶ stdout (unchanged)
                               └─ large ─▶ scrub ▶ hash ─┬─ seen ─▶ "unchanged since rNNN"
                                                         └─ new ──▶ detect/unwrap ▶ Parquet ▶ kq.artifacts + view ▶ handle line
kq describe ──▶ SUMMARIZE (one call, per-column stats)
kq q ──▶ read-only DuckDB ─┬─ small ─▶ rows
                           └─ large ─▶ q### artifact + edges ▶ handle line
kq commit ──▶ DuckDB (write) ──▶ kq.edges, new artifact version
every command ──▶ kq.events (OTel span shape) ──▶ optional OTLP exporter
kq view ──▶ view.html (DuckDB-WASM + embedded Parquet)
```

## Stack decisions

| Layer | Chosen | Alternatives considered | Why | Source |
|---|---|---|---|---|
| Kernel / query engine | DuckDB Python 1.5.x | SQLite, pandas in a pickled namespace | Reads CSV/JSON/Parquet natively; exposes its SQL parser via `json_serialize_sql`, which gives exact table references for lineage; read-only connections block writes. Behaviour verified locally on 1.5.6. | https://pypi.org/project/duckdb/ |
| Artifact format | Parquet, one file per artifact version | DuckDB native tables only, Arrow IPC | Readable by DuckDB-WASM, pandas, Polars, Spark; immutable files make versioning trivial. | https://npmjs.com/@duckdb/duckdb-wasm |
| Table snapshots (v1.1, flag) | DuckLake with a DuckDB catalog | Iceberg | Snapshots and time travel over Parquet with a SQL catalog; a DuckDB catalog limits you to a single client, which matches one session. | https://ducklake.select, https://ducklake.select/docs/stable/duckdb/usage/time_travel.html |
| Event shape | OTel GenAI `execute_tool` span | Custom JSON log | Any OTel backend can read sessions without a custom viewer. Conventions are **Development** status; isolate attribute names in one module. | https://github.com/open-telemetry/semantic-conventions-genai (`docs/gen-ai/gen-ai-spans.md`) |
| OTLP export (optional extra) | `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-http` 1.45.x | gRPC exporter | HTTP exporter has no gRPC native dependency. | https://pypi.org/project/opentelemetry-sdk/ |
| Viewer | `@duckdb/duckdb-wasm@1.32.0` from jsDelivr | Server-side rendering, Datasette | Zero server; same SQL as the CLI. 1.32.0 is the latest non-dev release (2025-12-16); `latest` tag is a dev build. | https://npmjs.com/@duckdb/duckdb-wasm |
| CLI framework | `argparse` (stdlib) | Typer, Click | Cold start matters: agents call `kq` dozens of times per session. Zero extra dependency. | — |
| Packaging | uv tool from git | pipx, PyPI | `uvx --from git+https://…` and `uv tool install git+https://…` both work without publishing. | https://docs.astral.sh/uv/guides/tools/ |
| Skill format | Agent Skills spec | Agent-specific rule files | One `SKILL.md` works across skills-capable agents. `name` must be lowercase, ≤ 64 chars, and match the folder name. | https://github.com/agentskills/agentskills (`docs/specification.mdx`) |

> 💡 DuckDB's CSV sniffer accepts plain text as single-column CSV (verified: `sniff_csv` on a log file returns delimiter `,`). Type detection therefore uses explicit rules, below, not "try CSV and see".

## Repository layout

```text
kq/
├── pyproject.toml            # [project.scripts] kq = "kq.cli:main"; extra: otel
├── src/kq/
│   ├── cli.py                # argparse entry point, subcommand dispatch, exit codes
│   ├── session.py            # session id, paths, lock retry
│   ├── store.py              # schema creation, migrations, artifact registration, views
│   ├── capture.py            # kq run: spool, threshold, exit-code mirroring
│   ├── detect.py             # type detection rules
│   ├── summarize.py          # deterministic 1-line summaries
│   ├── scrub.py              # secret patterns and redaction
│   ├── lineage.py            # SQL ref extraction, SELECT-only check, staleness
│   ├── query.py              # kq q (budget, spill), kq describe, SQL error hints
│   ├── events.py             # event rows
│   ├── otel_map.py           # the ONLY place OTel attribute names appear
│   ├── otel_export.py        # optional OTLP export, lazy-imported
│   └── view/
│       ├── render.py
│       └── template.html
├── skill/kq/SKILL.md         # Agent Skill (folder name must equal skill name)
├── .claude/skills/           # Claude Code project skills for building kq: kq-phase, kq-fixtures, verify
├── tests/
│   ├── fixtures/             # csv, tsv, json, ndjson, logs, secrets samples
│   └── test_*.py
├── eval/                     # task definitions + scorer (see docs/eval.md)
├── docs/eval.md
├── AGENTS.md
└── README.md
```

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | |
| uv | current | https://docs.astral.sh/uv/ |
| A coding agent with a shell and Agent Skills support | — | Claude Code, Codex, OpenCode, others |
| Network (viewer only) | — | `view.html` loads DuckDB-WASM and its Parquet extension from jsDelivr |

## Quick start

```bash
# 1. Install once so `kq` is on PATH (faster than uvx on every call)
uv tool install git+https://github.com/ejoliet/kq

# Or run without installing
uvx --from git+https://github.com/ejoliet/kq kq --version

# 2. Install the skill for your agent (Claude Code shown)
git clone https://github.com/ejoliet/kq /tmp/kq && cp -r /tmp/kq/skill/kq ~/.claude/skills/kq

# 3. Use it
kq run -- kubectl get pods -A -o json
#  r001  table  1,204 rows × 4 cols  items[] kind=List: metadata(STRUCT), spec(STRUCT), status(STRUCT)…
kq describe r001
kq q "select status.phase, count(*) from r001 group by 1"
kq commit failing_pods "select metadata.name from r001 where status.phase <> 'Running'"
kq view   # prints the path to view.html
```

## CLI contract

All commands accept `--session <id>`; default session is derived from the current directory (below). kq's own messages go to stderr; data goes to stdout.

| Command | Behaviour | Output (stdout) |
|---|---|---|
| `kq run [--as NAME] -- <cmd…>` | Runs `<cmd>` with the user's shell environment, no shell interpolation (argv as given). Stderr passes through live, uncaptured. If stdout ≤ threshold: print it unchanged, store nothing, log an event. Else: store an artifact, unless dedup applies. `--as NAME` stores under a chosen handle, creating a new version if content changed. Exit code always mirrors `<cmd>`. | Small: the raw stdout. Large: one handle line, or `unchanged since <handle> v<N>`. |
| `kq index [--all]` | Lists current artifact versions, newest first, max 30 rows (`--all` lifts the cap). Unnamed `r###`/`q###` artifacts that feed a named artifact are hidden unless `--all`. | `handle  type  shape  age  stale?  summary` |
| `kq describe <handle>` | DuckDB `SUMMARIZE` over the artifact. Text artifacts add the 5 most frequent first tokens of `line`. | One row per column: `name  type  null%  ~distinct  min  max` (min/max truncated to 24 chars) |
| `kq q "<SQL>" [--limit N] [--format table\|csv\|json]` | Read-only SQL over artifact views and `kq.*` tables. Default limit 50 rows, table format, cells truncated to 80 chars. If the rendered result exceeds the threshold, the full result (without the row limit) is stored as `q###` (edges recorded as for `commit`) and a handle line is printed instead. On SQL error, the referenced handles' columns and types are appended to the error. | Rows + `(N of M rows)` footer, or a handle line |
| `kq commit NAME "<SQL>"` | SELECT only. Materialises result as a new artifact version, records edges to every referenced handle at its current version. | Handle line |
| `kq stale` | Lists stale current artifacts and the upstream that changed. | `handle vN ← upstream vM (now vK)` |
| `kq view [--out PATH]` | Writes `view.html` into the session directory (or PATH). | The file path |
| `kq session new [NAME] \| list \| use ID` | `new` creates and selects a session; `use` pins one for this directory; `list` shows id, dir, artifacts, last activity. | Table |
| `kq --version` | | Version string |

**Handle line format** (stable, parsed by the eval):

```text
<handle>  <kind>  <shape>  <summary>
r003  table  48,120 rows × 6 cols  ra(DOUBLE), dec(DOUBLE), mag(FLOAT), …
r004  text  2,311 lines  first: "2026-10-08 INFO starting"; 14 ERROR, 3 WARN
unchanged since r003 v1
```

**Handles.** Runs get `r001`, `r002`, …; spilled queries get `q001`, `q002`, … per session. Names from `--as` or `commit` must match `^[a-z][a-z0-9_]{0,62}$` and must not start with `kq_`, or be `r`/`q` followed only by digits.

**Sessions.** Id = `<basename(cwd)>-<first 8 hex of sha256(realpath(cwd))>`. Directory: `${KQ_HOME:-$XDG_DATA_HOME/kq or ~/.local/share/kq}/sessions/<id>/` containing `session.duckdb` (DuckDB names the catalog after the file; a file named `kq.duckdb` would make every `kq.events` reference ambiguous with the metadata schema), `artifacts/<handle>.v<N>.parquet`, `view.html`. `kq session use` writes the pinned id to `<session dir of cwd>/pinned`.

**Type detection** (first match wins, on scrubbed bytes):

| Rule | Result |
|---|---|
| JSON object whose only array-of-objects value is under one key (for example `items`, `Contents`, `Reservations`) | `table` of that array's elements; `envelope_key` recorded; other top-level scalars kept in the summary (for example `kind=List`) |
| Parses as a JSON array of objects, or another JSON object | `table` from `read_json` (object → 1 row) |
| Every non-empty line parses as a JSON object | `table` from `read_json(format='newline_delimited')` |
| `sniff_csv` finds ≥ 2 columns, delimiter `,` or tab, and ≥ 95% of the first 1,000 lines have that column count | `table` from `read_csv` |
| Anything else | `text`: table `(line_no BIGINT, line VARCHAR)`; bytes decoded as UTF-8 with replacement characters |

**Summaries** are deterministic, ≤ 120 chars, no model calls. Table: rows × cols plus the first column names and types, prefixed by `<envelope_key>[]` when unwrapped. Text: line count, first non-empty line (≤ 40 chars), counts of lines matching `ERROR|FATAL|Traceback` and `WARN`.

## Configuration

| Env var | Type | Default | Purpose |
|---|---|---|---|
| `KQ_HOME` | path | `$XDG_DATA_HOME/kq` or `~/.local/share/kq` | Root for sessions |
| `KQ_SESSION` | string | derived from cwd | Force a session id |
| `KQ_THRESHOLD_TOKENS` | int | `2000` | Store above this estimate (`bytes / 4`); also the `kq q` output budget |
| `KQ_MAX_BYTES` | int | `2147483648` | Hard cap on captured stdout |
| `KQ_LOCK_TIMEOUT_S` | float | `5` | Retry window when another `kq` holds the write lock |
| `KQ_VIEW_EMBED_MAX_MB` | int | `25` | Total Parquet bytes embedded in `view.html`; larger artifacts are listed with metadata only |
| `KQ_OTLP_ENDPOINT` | URL | unset | If set and the `otel` extra is installed, export each event via OTLP/HTTP |
| `KQ_OTLP_TIMEOUT_S` | float | `2` | Export timeout; export failure never fails a command |

No secrets are read or required.

## Store schema

All metadata lives in schema `kq`. Artifact views live in `main`, one per handle, pointing at the current version's Parquet file.

**`kq.events`** — append-only; one row per CLI invocation.

| Column | Type | Notes |
|---|---|---|
| `event_id` | VARCHAR PK | uuid4 hex |
| `trace_id` | VARCHAR | 32 hex; fixed per session (sha256 of session id, first 32 hex) |
| `span_id` | VARCHAR | 16 hex, random |
| `parent_span_id` | VARCHAR | NULL in v1 |
| `name` | VARCHAR | `execute_tool kq.<op>` |
| `op` | VARCHAR | `run`, `q`, `commit`, `index`, `stale`, `view`, `session` |
| `started_at` / `ended_at` | TIMESTAMPTZ | |
| `status` | VARCHAR | `OK` or `ERROR` |
| `error_type` | VARCHAR | kq error code or `exit_<n>` for wrapped commands |
| `attributes` | JSON | See OTel mapping |

**`kq.artifacts`** — one row per artifact version. Versions are immutable.

| Column | Type | Notes |
|---|---|---|
| `handle` | VARCHAR | PK part |
| `version` | INTEGER | PK part, starts at 1 |
| `is_current` | BOOLEAN | exactly one TRUE per handle |
| `kind` | VARCHAR | `table` or `text` |
| `source_format` | VARCHAR | `json`, `ndjson`, `csv`, `tsv`, `text`, `sql` |
| `envelope_key` | VARCHAR | JSON key unwrapped at capture, else NULL |
| `content_sha256` | VARCHAR | hash of scrubbed stdout (run) or of the Parquet file (commit, q); used for dedup |
| `path` | VARCHAR | relative to session dir |
| `n_rows` / `n_cols` | BIGINT / INTEGER | |
| `bytes_raw` | BIGINT | captured stdout size before scrubbing |
| `schema` | JSON | `[{"name":…,"type":…}]` |
| `summary` | VARCHAR | ≤ 120 chars |
| `producer` | VARCHAR | `run`, `commit`, or `q` (spilled query) |
| `producer_text` | VARCHAR | scrubbed argv (run) or SQL (commit, q) |
| `exit_code` | INTEGER | NULL for commits |
| `redactions` | INTEGER | count of scrubbed matches |
| `event_id` | VARCHAR | FK → events |
| `created_at` | TIMESTAMPTZ | |

**`kq.edges`** — provenance, written by `commit` and by spilled `q`.

| Column | Type | Notes |
|---|---|---|
| `dst_handle`, `dst_version` | VARCHAR, INTEGER | the derived artifact |
| `src_handle`, `src_version` | VARCHAR, INTEGER | the version read at commit time |
| `event_id` | VARCHAR | |

PK: `(dst_handle, dst_version, src_handle)`.

**`kq.meta`** — `(key VARCHAR PK, value VARCHAR)`; holds `schema_version`.

**Lineage extraction.** `json_serialize_sql(sql)` returns the parse tree; collect every node with `type = 'BASE_TABLE'` and empty `schema_name` whose `table_name` is a known handle. If the result has `"error": true`, the statement is not a single SELECT and is rejected. Verified on DuckDB 1.5.6: joins and subqueries yield all references; `CREATE` statements return `error: true`.

## OTel span mapping

Source: `docs/gen-ai/gen-ai-spans.md` in https://github.com/open-telemetry/semantic-conventions-genai (status **Development**, read 2026-10-08).

| Span field / attribute | Value | Spec level |
|---|---|---|
| Span name | `execute_tool kq.<op>` (spec: `execute_tool {gen_ai.tool.name}`) | SHOULD |
| Span kind | `INTERNAL` | SHOULD |
| `gen_ai.operation.name` | `execute_tool` | Required |
| `gen_ai.tool.name` | `kq.run`, `kq.q`, `kq.commit`, … | Required |
| `gen_ai.conversation.id` | session id | Conditionally required |
| `gen_ai.tool.call.id` | `event_id` | Recommended |
| `error.type` | kq error code or `exit_<n>` | Conditionally required on error |
| `kq.artifact.handle`, `kq.artifact.version` | when an artifact is written | custom |
| `kq.bytes`, `kq.stored` (bool), `kq.redactions`, `kq.exit_code` | | custom |

Not set: `gen_ai.tool.call.arguments` and `gen_ai.tool.call.result` (opt-in; would copy command lines and data out of the session).

## Secret scrubbing

Applied to captured stdout before any disk write, and to argv/SQL before storing `producer_text` or event attributes. Matches are replaced with `[REDACTED:<kind>]` and counted.

| Kind | Pattern (summary) |
|---|---|
| `aws_key_id` | `\b(AKIA|ASIA)[0-9A-Z]{16}\b` |
| `aws_secret` | 40-char base64-ish value following `aws_secret_access_key` or `SecretAccessKey` |
| `github_token` | `\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b`, `\bgithub_pat_[A-Za-z0-9_]{22,}\b` |
| `slack_token` | `\bxox[abprs]-[A-Za-z0-9-]{10,}` |
| `private_key` | `-----BEGIN [A-Z ]*PRIVATE KEY-----` through the matching END line |
| `bearer` | `(?i)\bauthorization:\s*bearer\s+\S+` |
| `jwt` | three base64url segments starting `eyJ` |
| `kv_secret` | `(?i)\b(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+` (value only) |

> ⚠️ **Limits.** Pattern-based scrubbing misses unknown token formats and secrets split across lines. Small outputs that pass through are not stored, so they are not scrubbed: they go straight to the agent, as they would without `kq`. Do not share `view.html` from sessions that touched credentials without reviewing it.

## Error handling

kq errors print `kq: <CODE>: <message>` to stderr. `kq run` always exits with the wrapped command's code, even when kq fails internally.

| Code | Exit (non-`run`) | When | Behaviour |
|---|---|---|---|
| `E_USAGE` | 2 | Bad arguments, invalid handle name | |
| `E_LOCKED` | 3 | Write lock not acquired within `KQ_LOCK_TIMEOUT_S` | Retry with backoff (50 ms → 800 ms). For `run`: print raw stdout instead of storing. |
| `E_SQL_REJECTED` | 4 | `q`/`commit` SQL is not a single SELECT | |
| `E_SQL` | 4 | DuckDB execution error | DuckDB message passed through, followed by `columns of <handle>: name TYPE, …` for each referenced handle (max 30 columns each) |
| `E_UNKNOWN_HANDLE` | 5 | Referenced handle not found | Suggest closest handle |
| `E_TOO_LARGE` | — | stdout exceeds `KQ_MAX_BYTES` | Keep the first `KQ_MAX_BYTES`, mark `truncated` in summary |
| `E_STORE` | 6 | Store unreadable or schema migration failed | For `run`: fall back to raw stdout |
| `E_INTERNAL` | 70 | Anything else | For `run`: fall back to raw stdout |

## Testing

```bash
uv run pytest -q          # all suites, offline
uv run ruff check . && uv run ruff format --check .
```

| Suite | Covers |
|---|---|
| `test_detect.py` | Each rule in the detection table, including plain text that the CSV sniffer would accept, kubectl `items` and AWS `Contents` envelopes, objects with two array keys (no unwrap) |
| `test_capture.py` | Threshold boundary, exit-code mirroring, stderr pass-through, fallback to raw stdout on store failure, `KQ_MAX_BYTES` truncation |
| `test_scrub.py` | Every pattern, positive and negative fixtures; argv scrubbing |
| `test_lineage.py` | Refs from joins, CTEs, subqueries; rejection of non-SELECT; ignores `kq.*` tables |
| `test_query.py` | `q` spill above budget (full result stored, edges written), error hints list correct columns, `describe` on table and text artifacts |
| `test_dedup.py` | Identical re-run → no new version, no staleness; changed output → new version |
| `test_stale.py` | Direct and transitive staleness after `run --as` and re-`commit` |
| `test_store.py` | Schema creation, version immutability, one current version per handle, lock retry |
| `test_events.py` | OTel field mapping matches the table above |
| `test_view.py` | HTML contains embedded Parquet under the cap and metadata-only rows above it |
| `test_cli.py` | Handle-line format, `index` cap and hiding of superseded unnamed artifacts, `q` limit and formats |

Rules: no network, no real cloud CLIs. Wrapped commands in tests are `python -c` scripts that print fixtures.

## Non-goals (v1)

- MCP server or any long-running daemon.
- Re-running captured commands, automatically or on request.
- Capturing stderr, interactive commands, or TTY output.
- Python scratchpad over artifacts (SQL only).
- DuckLake snapshots, OpenLineage export (v1.1); Iceberg, DuckDB Quack (out of scope).
- Cross-machine or multi-user sessions.
- LLM-generated summaries.
- Agent-specific hooks that force capture (investigated in v1.1, below).

## Roadmap (v1.1)

Ordered by expected token savings. Each ships only if the eval shows the gain.

| Feature | Contract | Notes |
|---|---|---|
| `kq diff <handle> [--from N] [--to M]` | Rows added and removed between two versions (`EXCEPT` both ways), default previous → current; spills above budget like `q` | Text artifacts compare on `line`, ignoring `line_no` |
| Log templating | Text artifacts get a companion table `<handle>__tpl (template, count, first_line_no, level)`; summary becomes `N lines, K templates, E with ERROR` | Start with built-in masking (numbers, hex, UUIDs, IPs, timestamps → placeholders, group by result). `drain3` is the reference algorithm, but its last PyPI release is 0.9.11 from 2022-07-17; adopt only if masking underperforms |
| `kq run --ttl DURATION` | Reuse the newest artifact from the same scrubbed argv in this session if younger than DURATION; prints `cached <handle> (age)` | Opt-in only; the agent must ask for it. Never default |
| `kq export [--out PATH]` | `tar.gz` of the session dir (DuckDB file, Parquet, `view.html`) | For bug reports and handoff; same scrubbing caveats as `view` |
| Agent hooks | Per-agent adapter that routes large tool results through `kq` | Confirm each agent's hook API can rewrite or intercept a command before building |
| DuckLake snapshots | Behind `KQ_DUCKLAKE=1` | See stack table |
| OpenLineage export | Emit run events from `kq.edges` | |

## Open questions

1. **OTel GenAI pinning.** The conventions repo has Development status; release tags could not be checked (GitHub API rate-limited during research). Pin `otel_map.py` to a commit SHA of `semantic-conventions-genai` and record it in a comment.
2. **Querying old versions.** v1 views expose only the current version. Add `<handle>__v<N>` views, or a `kq q --at` flag?
3. **Large text artifacts.** Is `ilike`/`regexp_matches` plus `describe` enough, or is log templating needed in v1? Decide from eval tasks 2 and 11.
4. **Session retention.** No TTL in v1. Add `kq session prune --older-than 30d`?
5. **Skill install paths** for agents other than Claude Code: confirm each agent's skills directory before documenting it.

## Agent build instructions

> Implement end-to-end from this README and `AGENTS.md`. Resolve Open Question 1 in Phase 6; the others are deferred.

### Build order

| Phase | Deliverable | Done when |
|---|---|---|
| 0 | `pyproject.toml` (src layout, `kq = "kq.cli:main"`, `otel` extra), `cli.py` skeleton, ruff + pytest config | `uv run kq --version` prints the version; `uv run pytest -q` passes |
| 1 | `session.py`, `store.py` (schema, `kq.meta`, migrations, lock retry), `events.py` | `test_store.py`, `test_events.py` pass |
| 2 | `capture.py`, `detect.py` (incl. envelope unwrap), `scrub.py`, `summarize.py`; `kq run` with dedup | `test_capture.py`, `test_detect.py`, `test_scrub.py`, `test_dedup.py` pass |
| 3 | `lineage.py`, `query.py`; `kq q` (budget, spill, error hints), `kq describe`, `kq commit`, `kq stale` | `test_lineage.py`, `test_query.py`, `test_stale.py` pass |
| 4 | `kq index`, `kq session` | `test_cli.py` passes |
| 5 | `view/render.py` + `template.html`; `kq view` | `test_view.py` passes |
| 6 | `otel_map.py` pinned to a commit SHA; `otel_export.py` lazy-loaded | `test_events.py` passes with and without the extra |
| 7 | `skill/kq/SKILL.md` placed as delivered (edit only if a command changed); `eval/` scaffolding per `docs/eval.md` | `uv run python -m eval.score --help` works |

### File map

| File | Purpose | Key symbols |
|---|---|---|
| `cli.py` | Parse args, dispatch, map errors to exit codes | `main()`, `KqError` |
| `session.py` | Resolve id and paths, pinned session | `resolve_session()`, `SessionPaths` |
| `store.py` | DuckDB connections, schema, artifact registration | `open_rw()`, `open_ro()`, `register_artifact()`, `refresh_view()` |
| `capture.py` | Spool stdout, threshold, exit code | `run_and_capture()` |
| `detect.py` | Detection rules | `detect(path) -> Detected` |
| `summarize.py` | 1-line summaries | `summarize(conn, artifact) -> str` |
| `scrub.py` | Redaction | `scrub_bytes()`, `scrub_text()`, `PATTERNS` |
| `lineage.py` | Parse refs, SELECT check, staleness | `extract_refs()`, `stale_artifacts()` |
| `query.py` | Query execution, output budget, spill, describe, error hints | `run_query()`, `describe()`, `schema_hint()` |
| `events.py` | Event rows | `record_event()` |
| `otel_map.py` | Event → span attributes | `to_span_attributes()`, `SEMCONV_COMMIT` |
| `otel_export.py` | Optional export | `export_event()` |
| `view/render.py` | Build `view.html` | `render_view()` |

### Acceptance criteria

- [ ] `uv run pytest -q` passes offline; `ruff check` and `ruff format --check` pass.
- [ ] `kq run -- python -c "print('x')"` prints `x` and exits 0; `kq run -- python -c "import sys; sys.exit(3)"` exits 3.
- [ ] A 1 MB NDJSON fixture through `kq run` prints exactly one handle line and creates one Parquet file.
- [ ] With the store directory made read-only, `kq run` still prints the raw stdout and mirrors the exit code.
- [ ] `kq q "delete from r001"` exits 4 with `E_SQL_REJECTED`.
- [ ] After `kq run --as src …` twice, a commit derived from `src` v1 is listed by `kq stale`.
- [ ] A fixture containing each secret kind produces zero raw matches in the Parquet file, `kq.events`, and `kq.artifacts`.
- [ ] `kq index` on a session with 10 artifacts completes in < 300 ms (measured by Emmanuel, below).
- [ ] `kq view` output contains embedded data for artifacts under the cap.
- [ ] Running the same large command twice prints `unchanged since r001 v1` the second time and adds no Parquet file.
- [ ] A kubectl-style fixture with `items` produces a table with one row per item and `envelope_key = 'items'`.
- [ ] `kq q "select * from r001"` on a 100k-row artifact prints one `q###` handle line, not rows.
- [ ] `kq q "select nosuchcol from r001"` exits 4 and lists `r001`'s columns.
- [ ] `kq describe r001` prints one row per column in one call.
- [ ] `skill/kq/SKILL.md` frontmatter `name` is `kq` and validates with `skills-ref`.

### Checks Emmanuel runs (not the agent)

```bash
# Packaging from GitHub (after push)
uvx --from git+https://github.com/ejoliet/kq kq --version

# Cold-start budget
for i in 1 2 3; do /usr/bin/time -p kq index > /dev/null; done

# Viewer (opens in default browser)
kq view | xargs open        # macOS
kq view | xargs xdg-open    # Linux

# Skill validation (skills-ref from github.com/agentskills/agentskills)
skills-ref validate ./skill/kq

# Optional OTLP export into a local Jaeger
docker run --rm -d -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one
KQ_OTLP_ENDPOINT=http://localhost:4318 kq run -- cat tests/fixtures/pods.json
```

## Next steps

1. Implement Phases 0–3 and run the cold-start and packaging checks.
2. Run the evaluation in `docs/eval.md` before building Phases 5–6.
3. Decide Open Questions 2–3 from eval results.
4. Build the v1.1 roadmap in order, re-running the eval after each feature.
