"""kq index: list current artifact versions."""

from __future__ import annotations

import time

from .session import resolve_session
from .store import open_ro

CAP = 30


def _age(created_epoch: float) -> str:
    seconds = max(0.0, time.time() - created_epoch)
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return f"{int(seconds)}s"


def cmd_index(session: str | None, show_all: bool) -> int:
    paths = resolve_session(session, create=False)
    conn = open_ro(paths)
    try:
        # AIDEV-NOTE: epoch() keeps TIMESTAMPTZ out of Python — DuckDB needs pytz to convert one,
        # and invariant 6 forbids a new runtime dependency.
        rows = conn.execute(
            """SELECT handle, version, kind, n_rows, n_cols, epoch(created_at), summary
               FROM kq.artifacts WHERE is_current
               ORDER BY created_at DESC"""
        ).fetchall()
    finally:
        conn.close()

    if not show_all:
        rows = rows[:CAP]
    for handle, version, kind, n_rows, n_cols, created, summary in rows:
        shape = f"{n_rows:,} lines" if kind == "text" else f"{n_rows:,} rows × {n_cols:,} cols"
        print(f"{handle} v{version}  {kind}  {shape}  {_age(created)}  {summary}")
    return 0
