---
name: kq-fixtures
description: Rules for kq test fixtures, fake secrets, and wrapped test commands. Use when adding or editing files under tests/, or writing tests that feed command output to kq.
paths: tests/**
---

# kq test fixtures

## Rules

1. **No literal secret-shaped strings anywhere in the repo.** Build fake tokens at runtime in `tests/secrets.py` from fragments, for example `"gh" + "p_" + "A" * 36`. Never write a full `ghp_…`, `AKIA…`, `xoxb-…`, JWT, or PEM private-key block into any file, fixture, or docstring. GitHub secret scanning can block the push, and real-looking tokens in a public repo get reported.
2. **Small fixtures are committed; large ones are generated.** Commit files ≤ 200 KB in `tests/fixtures/`. Generate anything larger in a session-scoped pytest fixture with a fixed seed (`tests/fixtures/make.py`), written to `tmp_path_factory`, never committed.
3. **Exercise thresholds with settings, not size.** Set `KQ_THRESHOLD_TOKENS` low (for example `50`) with `monkeypatch.setenv` instead of making big files.
4. **Isolate state.** Every test sets `KQ_HOME` to its own `tmp_path`. No test reads `~/.local/share/kq`.
5. **Wrapped commands are Python, never real CLIs.** Use `[sys.executable, "-c", "import sys; sys.stdout.buffer.write(open(PATH, 'rb').read())"]`, or `sys.exit(N)` for exit-code tests. No `kubectl`, `aws`, `gh`, or `curl`.
6. **Offline only.** No network imports in tests.

## Required fixture shapes

| File | Shape | Exercises |
|---|---|---|
| `pods.json` | `{"apiVersion", "kind": "List", "items": [...]}` | Envelope unwrap via `items` |
| `s3_list.json` | `{"Contents": [...], "IsTruncated": false, "KeyCount": N}` | Unwrap via `Contents`, scalars kept in summary |
| `two_arrays.json` | Object with two arrays of objects | No unwrap: one-row table |
| `events.ndjson` | One JSON object per line | NDJSON rule |
| `catalog.csv`, `catalog.tsv` | ≥ 2 columns, header | CSV/TSV rule |
| `ragged.csv` | Under 95% consistent column count | Falls through to `text` |
| `plain.log` | Free text that `sniff_csv` accepts as one column | Must become `text`, not `table` |
| `mixed.log` | `INFO`/`WARN`/`ERROR`/`Traceback` lines | Text summary counts |
| `non_utf8.bin` | Invalid UTF-8 bytes | Decoded with replacement characters, stored as `text` |
| `empty.txt` | Zero bytes | Pass-through, nothing stored |
| Generated in `tests/secrets.py` | One sample per scrub kind, plus near-misses | Scrub positives and negatives |
