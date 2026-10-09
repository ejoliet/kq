"""Type detection rules (README "Type detection" table, first match wins)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# AIDEV-NOTE: read_json allocates this buffer up front, so it cannot be KQ_MAX_BYTES; 256 MB is
# the largest single JSON object kq will parse (DuckDB's own default is 16 MB).
MAX_JSON_OBJECT = 268_435_456
SNIFF_LINES = 1000
# Control characters that never appear in text we want to split on, used to read a log file
# as a one-column table without the CSV sniffer touching it.
TEXT_DELIM = "\x1f"
TEXT_QUOTE = "\x1e"


@dataclass
class Detected:
    kind: str  # "table" or "text"
    source_format: str  # json | ndjson | csv | tsv | text
    select: str  # a SELECT over the stored file
    envelope_key: str | None = None
    scalars: dict = field(default_factory=dict)


def _lit(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _json_text(data: bytes) -> object | None:
    head = data.lstrip()[:1]
    if head not in (b"{", b"["):
        return None
    try:
        return json.loads(data)
    except ValueError:
        return None


def _is_ndjson(data: bytes) -> bool:
    lines = [ln for ln in data.splitlines() if ln.strip()]
    if not lines:
        return False
    # AIDEV-NOTE: ponytail: parse the first 1000 lines, prefix-check the rest. Full parsing of a
    # 1 GB capture costs more than the rule is worth; a file whose tail stops being JSON fails at
    # read_json time and falls back through the same error path as a malformed capture.
    for ln in lines[:SNIFF_LINES]:
        s = ln.strip()
        if not s.startswith(b"{"):
            return False
        try:
            if not isinstance(json.loads(s), dict):
                return False
        except ValueError:
            return False
    return all(ln.strip().startswith(b"{") for ln in lines[SNIFF_LINES:])


def _sniff_csv(conn, path: Path, data: bytes) -> str | None:
    """Return 'csv', 'tsv', or None. Explicit rules: never 'the sniffer succeeded'."""
    try:
        row = conn.execute(
            f"SELECT Delimiter, Columns FROM sniff_csv({_lit(str(path))})"
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    delim, columns = row[0], row[1]
    n_cols = len(columns or [])
    if n_cols < 2 or delim not in (",", "\t"):
        return None
    lines = [ln for ln in data.splitlines()[:SNIFF_LINES] if ln.strip()]
    if not lines:
        return None
    d = delim.encode()
    consistent = sum(1 for ln in lines if ln.count(d) + 1 == n_cols)
    if consistent / len(lines) < 0.95:
        return None
    return "tsv" if delim == "\t" else "csv"


def _as_text(path: Path) -> Detected:
    # AIDEV-NOTE: rewrite the file as valid UTF-8 (replacement chars) so DuckDB's reader never
    # rejects a binary capture; the stored artifact is what the agent will query.
    decoded = path.read_bytes().decode("utf-8", "replace")
    path.write_text(decoded, encoding="utf-8")
    select = (
        "SELECT row_number() OVER () AS line_no, line FROM read_csv("
        f"{_lit(str(path))}, delim={_lit(TEXT_DELIM)}, quote={_lit(TEXT_QUOTE)}, "
        f"escape={_lit(TEXT_QUOTE)}, header=false, columns={{'line': 'VARCHAR'}}, "
        "auto_detect=false, ignore_errors=true)"
    )
    return Detected("text", "text", select)


def detect(conn, path: Path) -> Detected:
    data = path.read_bytes()
    lit = _lit(str(path))

    obj = _json_text(data)
    if isinstance(obj, dict):
        arrays = [
            k
            for k, v in obj.items()
            if isinstance(v, list) and v and all(isinstance(e, dict) for e in v)
        ]
        if len(arrays) == 1:
            key = arrays[0]
            scalars = {k: v for k, v in obj.items() if not isinstance(v, (list, dict))}
            select = (
                f"SELECT u.* FROM (SELECT unnest({_ident(key)}) AS u FROM "
                f"read_json({lit}, maximum_object_size={MAX_JSON_OBJECT})) t"
            )
            return Detected("table", "json", select, key, scalars)
        return Detected(
            "table",
            "json",
            f"SELECT * FROM read_json({lit}, maximum_object_size={MAX_JSON_OBJECT})",
        )
    if isinstance(obj, list) and obj and all(isinstance(e, dict) for e in obj):
        return Detected(
            "table",
            "json",
            f"SELECT * FROM read_json({lit}, maximum_object_size={MAX_JSON_OBJECT})",
        )

    if _is_ndjson(data):
        select = (
            f"SELECT * FROM read_json({lit}, format='newline_delimited', "
            f"maximum_object_size={MAX_JSON_OBJECT})"
        )
        return Detected("table", "ndjson", select)

    fmt = _sniff_csv(conn, path, data)
    if fmt:
        return Detected("table", fmt, f"SELECT * FROM read_csv({lit})")

    return _as_text(path)
