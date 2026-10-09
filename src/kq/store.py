"""DuckDB connections, schema creation, artifact registration, views."""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from .cli import KqError
from .session import SessionPaths, lock_timeout

SCHEMA_VERSION = "1"

HANDLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

DDL = (
    "CREATE SCHEMA IF NOT EXISTS kq",
    'CREATE TABLE IF NOT EXISTS kq.meta("key" VARCHAR PRIMARY KEY, value VARCHAR)',
    """CREATE TABLE IF NOT EXISTS kq.events(
        event_id VARCHAR PRIMARY KEY,
        trace_id VARCHAR,
        span_id VARCHAR,
        parent_span_id VARCHAR,
        name VARCHAR,
        op VARCHAR,
        started_at TIMESTAMPTZ,
        ended_at TIMESTAMPTZ,
        status VARCHAR,
        error_type VARCHAR,
        attributes JSON)""",
    """CREATE TABLE IF NOT EXISTS kq.artifacts(
        handle VARCHAR,
        version INTEGER,
        is_current BOOLEAN,
        kind VARCHAR,
        source_format VARCHAR,
        envelope_key VARCHAR,
        content_sha256 VARCHAR,
        path VARCHAR,
        n_rows BIGINT,
        n_cols INTEGER,
        bytes_raw BIGINT,
        "schema" JSON,
        summary VARCHAR,
        producer VARCHAR,
        producer_text VARCHAR,
        exit_code INTEGER,
        redactions INTEGER,
        event_id VARCHAR,
        created_at TIMESTAMPTZ,
        PRIMARY KEY(handle, version))""",
    """CREATE TABLE IF NOT EXISTS kq.edges(
        dst_handle VARCHAR,
        dst_version INTEGER,
        src_handle VARCHAR,
        src_version INTEGER,
        event_id VARCHAR,
        PRIMARY KEY(dst_handle, dst_version, src_handle))""",
)


def valid_handle(name: str) -> bool:
    if not HANDLE_RE.match(name) or name.startswith("kq_"):
        return False
    return not re.match(r"^[rq][0-9]+$", name)


def _connect(path: Path, read_only: bool, timeout: float) -> duckdb.DuckDBPyConnection:
    # AIDEV-NOTE: retry only on lock contention; a permission/corruption error is E_STORE and
    # must surface immediately so `run` can fall back to raw stdout.
    deadline = time.monotonic() + timeout
    delay = 0.05
    while True:
        try:
            return duckdb.connect(str(path), read_only=read_only)
        except duckdb.Error as e:
            if "lock" not in str(e).lower():
                raise KqError("E_STORE", str(e).splitlines()[0]) from None
            if time.monotonic() >= deadline:
                raise KqError("E_LOCKED", f"write lock busy on {path}") from None
            time.sleep(delay)
            delay = min(delay * 2, 0.8)


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    for stmt in DDL:
        conn.execute(stmt)
    conn.execute(
        'INSERT INTO kq.meta("key", value) VALUES (?, ?) ON CONFLICT DO NOTHING',
        ["schema_version", SCHEMA_VERSION],
    )


def open_rw(paths: SessionPaths, timeout: float | None = None) -> duckdb.DuckDBPyConnection:
    paths.artifacts.mkdir(parents=True, exist_ok=True)
    conn = _connect(paths.db, False, lock_timeout() if timeout is None else timeout)
    try:
        ensure_schema(conn)
    except duckdb.Error as e:
        conn.close()
        raise KqError("E_STORE", f"schema creation failed: {e}") from None
    return conn


def open_ro(paths: SessionPaths) -> duckdb.DuckDBPyConnection:
    if not paths.db.exists():
        raise KqError("E_STORE", f"no store for session {paths.id}")
    return _connect(paths.db, True, lock_timeout())


def next_handle(conn: duckdb.DuckDBPyConnection, prefix: str) -> str:
    rows = conn.execute(
        "SELECT handle FROM kq.artifacts WHERE regexp_matches(handle, ?)",
        [f"^{prefix}[0-9]+$"],
    ).fetchall()
    n = max((int(h[0][1:]) for h in rows), default=0) + 1
    return f"{prefix}{n:03d}"


def current_version(conn: duckdb.DuckDBPyConnection, handle: str) -> int:
    row = conn.execute(
        "SELECT max(version) FROM kq.artifacts WHERE handle = ?", [handle]
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def find_duplicate(
    conn: duckdb.DuckDBPyConnection, content_sha: str, handle: str | None, producer_text: str
) -> tuple[str, int] | None:
    row = conn.execute(
        """SELECT handle, version FROM kq.artifacts
           WHERE content_sha256 = ? AND is_current
             AND (handle = ? OR producer_text = ?)
           ORDER BY created_at DESC LIMIT 1""",
        [content_sha, handle or "", producer_text],
    ).fetchone()
    return (row[0], int(row[1])) if row else None


def register_artifact(conn: duckdb.DuckDBPyConnection, row: dict[str, Any]) -> int:
    """Insert a new immutable version and flip is_current. Returns the new version."""
    handle = row["handle"]
    version = row.get("version") or current_version(conn, handle) + 1
    conn.execute("UPDATE kq.artifacts SET is_current = FALSE WHERE handle = ?", [handle])
    conn.execute(
        """INSERT INTO kq.artifacts VALUES (
            $handle, $version, TRUE, $kind, $source_format, $envelope_key, $content_sha256,
            $path, $n_rows, $n_cols, $bytes_raw, $schema, $summary, $producer, $producer_text,
            $exit_code, $redactions, $event_id, $created_at)""",
        {
            "handle": handle,
            "version": version,
            "kind": row["kind"],
            "source_format": row["source_format"],
            "envelope_key": row.get("envelope_key"),
            "content_sha256": row["content_sha256"],
            "path": row["path"],
            "n_rows": row["n_rows"],
            "n_cols": row["n_cols"],
            "bytes_raw": row["bytes_raw"],
            "schema": json.dumps(row["schema"]),
            "summary": row["summary"],
            "producer": row["producer"],
            "producer_text": row["producer_text"],
            "exit_code": row.get("exit_code"),
            "redactions": row.get("redactions", 0),
            "event_id": row.get("event_id"),
            "created_at": datetime.now(UTC),
        },
    )
    return version


def refresh_view(conn: duckdb.DuckDBPyConnection, handle: str, parquet_path: Path) -> None:
    literal = str(parquet_path).replace("'", "''")
    conn.execute(f"CREATE OR REPLACE VIEW main.{handle} AS SELECT * FROM read_parquet('{literal}')")
