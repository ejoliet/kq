"""Event rows: one per CLI invocation, shaped like an OpenTelemetry span."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import duckdb


def trace_id_for(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()[:32]


def now() -> datetime:
    return datetime.now(UTC)


def record_event(
    conn: duckdb.DuckDBPyConnection,
    session_id: str,
    op: str,
    *,
    started_at: datetime,
    ended_at: datetime | None = None,
    status: str = "OK",
    error_type: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> str:
    event_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO kq.events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            event_id,
            trace_id_for(session_id),
            os.urandom(8).hex(),
            None,
            f"execute_tool kq.{op}",
            op,
            started_at,
            ended_at or now(),
            status,
            error_type,
            json.dumps(attributes or {}),
        ],
    )
    return event_id
