"""Deterministic 1-line summaries and shape strings. No model calls."""

from __future__ import annotations

MAX_SUMMARY = 120


def clip(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def table_shape(n_rows: int, n_cols: int) -> str:
    return f"{n_rows:,} rows × {n_cols:,} cols"


def text_shape(n_rows: int) -> str:
    return f"{n_rows:,} lines"


def table_summary(columns: list[tuple[str, str]], envelope_key: str | None, scalars: dict) -> str:
    prefix = f"{envelope_key}[] " if envelope_key else ""
    if scalars:
        kv = " ".join(f"{k}={v}" for k, v in list(scalars.items())[:2])
        prefix = f"{prefix}{kv}: "
    cols = ", ".join(f"{name}({dtype})" for name, dtype in columns)
    return clip(prefix + cols, MAX_SUMMARY)


def text_summary(conn, view: str) -> str:
    first = conn.execute(f"SELECT line FROM {view} WHERE trim(line) <> '' LIMIT 1").fetchone()
    first_line = clip(first[0], 40) if first else ""
    errors, warns = conn.execute(
        f"""SELECT
              count(*) FILTER (WHERE regexp_matches(line, 'ERROR|FATAL|Traceback')),
              count(*) FILTER (WHERE regexp_matches(line, 'WARN'))
            FROM {view}"""
    ).fetchone()
    return clip(f'first: "{first_line}"; {errors} ERROR, {warns} WARN', MAX_SUMMARY)


def handle_line(handle: str, kind: str, shape: str, summary: str) -> str:
    return f"{handle}  {kind}  {shape}  {summary}"
