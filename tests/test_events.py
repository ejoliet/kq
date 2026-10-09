from __future__ import annotations

import json
import re

from kq.events import now, record_event, trace_id_for
from kq.store import open_rw


def test_event_row_has_otel_span_shape(kq_env):
    conn = open_rw(kq_env)
    started = now()
    event_id = record_event(
        conn,
        kq_env.id,
        "run",
        started_at=started,
        attributes={"kq.bytes": 10, "kq.stored": False},
    )
    row = conn.execute(
        """SELECT event_id, trace_id, span_id, parent_span_id, name, op,
                  started_at::VARCHAR, ended_at::VARCHAR, status, error_type, attributes
           FROM kq.events"""
    ).fetchone()
    conn.close()

    assert row[0] == event_id
    assert row[1] == trace_id_for(kq_env.id)
    assert re.fullmatch(r"[0-9a-f]{32}", row[1])
    assert re.fullmatch(r"[0-9a-f]{16}", row[2])
    assert row[3] is None
    assert row[4] == "execute_tool kq.run"
    assert row[5] == "run"
    assert row[6] is not None and row[7] is not None
    assert row[8] == "OK"
    assert row[9] is None
    assert json.loads(row[10]) == {"kq.bytes": 10, "kq.stored": False}


def test_trace_id_is_stable_per_session_and_span_ids_differ(kq_env):
    conn = open_rw(kq_env)
    record_event(conn, kq_env.id, "run", started_at=now())
    record_event(conn, kq_env.id, "index", started_at=now())
    traces, spans = zip(
        *conn.execute("SELECT trace_id, span_id FROM kq.events").fetchall(), strict=True
    )
    conn.close()
    assert len(set(traces)) == 1
    assert len(set(spans)) == 2


def test_error_event_records_error_type(kq_env):
    conn = open_rw(kq_env)
    record_event(conn, kq_env.id, "run", started_at=now(), status="ERROR", error_type="exit_3")
    assert conn.execute("SELECT status, error_type FROM kq.events").fetchone() == (
        "ERROR",
        "exit_3",
    )
    conn.close()
