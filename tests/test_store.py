from __future__ import annotations

import duckdb
import pytest

from kq import store
from kq.cli import KqError
from kq.store import current_version, next_handle, open_rw, register_artifact, valid_handle


def _row(handle: str, sha: str, version: int | None = None) -> dict:
    return {
        "handle": handle,
        "version": version,
        "kind": "table",
        "source_format": "csv",
        "envelope_key": None,
        "content_sha256": sha,
        "path": f"artifacts/{handle}.v1.parquet",
        "n_rows": 3,
        "n_cols": 2,
        "bytes_raw": 99,
        "schema": [{"name": "a", "type": "BIGINT"}],
        "summary": "a(BIGINT)",
        "producer": "run",
        "producer_text": "echo hi",
        "exit_code": 0,
        "redactions": 0,
        "event_id": None,
    }


def test_schema_created_with_version(kq_env):
    conn = open_rw(kq_env)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'kq'"
        ).fetchall()
    }
    assert {"meta", "events", "artifacts", "edges"} <= tables
    value = conn.execute("SELECT value FROM kq.meta WHERE \"key\" = 'schema_version'").fetchone()
    assert value[0] == store.SCHEMA_VERSION
    conn.close()


def test_schema_creation_is_idempotent(kq_env):
    open_rw(kq_env).close()
    conn = open_rw(kq_env)
    n = conn.execute("SELECT count(*) FROM kq.meta").fetchone()[0]
    assert n == 1
    conn.close()


def test_versions_are_immutable_and_one_current(kq_env):
    conn = open_rw(kq_env)
    assert register_artifact(conn, _row("src", "aaa")) == 1
    assert register_artifact(conn, _row("src", "bbb")) == 2
    rows = conn.execute(
        "SELECT version, is_current, content_sha256 FROM kq.artifacts ORDER BY version"
    ).fetchall()
    assert rows == [(1, False, "aaa"), (2, True, "bbb")]
    assert current_version(conn, "src") == 2
    conn.close()


def test_duplicate_version_rejected(kq_env):
    conn = open_rw(kq_env)
    register_artifact(conn, _row("src", "aaa"))
    with pytest.raises(duckdb.Error):
        register_artifact(conn, _row("src", "ccc", version=1))
    conn.close()


def test_next_handle_counts_per_prefix(kq_env):
    conn = open_rw(kq_env)
    assert next_handle(conn, "r") == "r001"
    register_artifact(conn, _row("r001", "aaa"))
    assert next_handle(conn, "r") == "r002"
    assert next_handle(conn, "q") == "q001"
    conn.close()


def test_lock_retry_then_success(kq_env, monkeypatch):
    calls = {"n": 0}
    real = duckdb.connect

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise duckdb.IOException("Could not set lock on file: Conflicting lock")
        return real(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", flaky)
    conn = open_rw(kq_env, timeout=5.0)
    assert calls["n"] == 3
    conn.close()


def test_lock_timeout_raises_e_locked(kq_env, monkeypatch):
    def always_locked(*args, **kwargs):
        raise duckdb.IOException("Could not set lock on file: Conflicting lock")

    monkeypatch.setattr(duckdb, "connect", always_locked)
    with pytest.raises(KqError) as e:
        open_rw(kq_env, timeout=0.1)
    assert e.value.code == "E_LOCKED"


def test_non_lock_error_is_e_store(kq_env, monkeypatch):
    def broken(*args, **kwargs):
        raise duckdb.IOException("Permission denied")

    monkeypatch.setattr(duckdb, "connect", broken)
    with pytest.raises(KqError) as e:
        open_rw(kq_env, timeout=5.0)
    assert e.value.code == "E_STORE"


@pytest.mark.parametrize("name", ["src", "failing_pods", "a", "a_1"])
def test_valid_handles(name):
    assert valid_handle(name)


@pytest.mark.parametrize("name", ["R1", "1abc", "kq_x", "r001", "q12", "with-dash", ""])
def test_invalid_handles(name):
    assert not valid_handle(name)
