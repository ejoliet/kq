"""kq run: spool stdout, apply the threshold, mirror the exit code, store the artifact."""

from __future__ import annotations

import hashlib
import shlex
import subprocess
import sys
import tempfile

from .cli import KqError, warn
from .detect import detect
from .events import now, record_event
from .scrub import scrub_bytes, scrub_text
from .session import SessionPaths, max_bytes, resolve_session, threshold_tokens
from .store import (
    current_version,
    find_duplicate,
    next_handle,
    open_rw,
    refresh_view,
    register_artifact,
    valid_handle,
)
from .summarize import handle_line, table_shape, table_summary, text_shape, text_summary


def run_and_capture(command: list[str], limit: int) -> tuple[int, bytes, bool]:
    """Run `command`, spooling stdout to a temp file. Stderr passes through live."""
    with tempfile.TemporaryFile() as spool:
        try:
            proc = subprocess.run(command, stdout=spool, stderr=None, check=False)
        except OSError as e:
            raise KqError("E_USAGE", f"cannot run {command[0]!r}: {e}") from None
        spool.seek(0)
        data = spool.read(limit + 1)
    truncated = len(data) > limit
    return proc.returncode, data[:limit], truncated


def _store(
    paths: SessionPaths,
    as_name: str | None,
    command: list[str],
    data: bytes,
    exit_code: int,
    truncated: bool,
) -> str:
    scrubbed, redactions = scrub_bytes(data)
    content_sha = hashlib.sha256(scrubbed).hexdigest()
    producer_text, _ = scrub_text(" ".join(shlex.quote(a) for a in command))

    conn = open_rw(paths)
    try:
        dup = find_duplicate(conn, content_sha, as_name, producer_text)
        if dup:
            record_event(
                conn,
                paths.id,
                "run",
                started_at=now(),
                attributes={
                    "kq.bytes": len(data),
                    "kq.stored": False,
                    "kq.dedup": True,
                    "kq.exit_code": exit_code,
                    "kq.artifact.handle": dup[0],
                    "kq.artifact.version": dup[1],
                },
            )
            return f"unchanged since {dup[0]} v{dup[1]}"

        handle = as_name or next_handle(conn, "r")
        version = current_version(conn, handle) + 1
        rel = f"artifacts/{handle}.v{version}.parquet"
        parquet = paths.dir / rel

        work = paths.artifacts / f".{handle}.v{version}.raw"
        work.write_bytes(scrubbed)
        try:
            det = detect(conn, work)
            literal = str(parquet).replace("'", "''")
            conn.execute(f"COPY ({det.select}) TO '{literal}' (FORMAT PARQUET)")
        finally:
            work.unlink(missing_ok=True)

        refresh_view(conn, handle, parquet)
        columns = [(r[0], r[1]) for r in conn.execute(f"DESCRIBE {handle}").fetchall()]
        n_rows = conn.execute(f"SELECT count(*) FROM {handle}").fetchone()[0]
        n_cols = len(columns)

        if det.kind == "text":
            shape = text_shape(n_rows)
            summary = text_summary(conn, handle)
        else:
            shape = table_shape(n_rows, n_cols)
            summary = table_summary(columns, det.envelope_key, det.scalars)
        if truncated:
            summary = f"{summary} [truncated]"

        event_id = record_event(
            conn,
            paths.id,
            "run",
            started_at=now(),
            attributes={
                "kq.bytes": len(data),
                "kq.stored": True,
                "kq.redactions": redactions,
                "kq.exit_code": exit_code,
                "kq.artifact.handle": handle,
                "kq.artifact.version": version,
            },
        )
        register_artifact(
            conn,
            {
                "handle": handle,
                "version": version,
                "kind": det.kind,
                "source_format": det.source_format,
                "envelope_key": det.envelope_key,
                "content_sha256": content_sha,
                "path": rel,
                "n_rows": n_rows,
                "n_cols": n_cols,
                "bytes_raw": len(data),
                "schema": [{"name": n, "type": t} for n, t in columns],
                "summary": summary,
                "producer": "run",
                "producer_text": producer_text,
                "exit_code": exit_code,
                "redactions": redactions,
                "event_id": event_id,
            },
        )
        return handle_line(handle, det.kind, shape, summary)
    finally:
        conn.close()


def cmd_run(session: str | None, as_name: str | None, command: list[str]) -> int:
    if as_name is not None and not valid_handle(as_name):
        raise KqError("E_USAGE", f"invalid handle name {as_name!r}")

    limit = max_bytes()
    exit_code, data, truncated = run_and_capture(command, limit)
    if truncated:
        warn(
            f"E_TOO_LARGE: stdout exceeded KQ_MAX_BYTES ({limit}); keeping the first {limit} bytes"
        )

    line = None
    if len(data) / 4 > threshold_tokens():
        # AIDEV-NOTE: invariant 1 — any failure here falls back to raw stdout and the wrapped
        # exit code. kq never swallows output.
        try:
            line = _store(resolve_session(session), as_name, command, data, exit_code, truncated)
        except KqError as e:
            warn(f"{e.code}: {e.message} (printing raw output)")
        except Exception as e:  # noqa: BLE001
            warn(f"E_INTERNAL: {e} (printing raw output)")

    if line is None:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    else:
        print(line)
    return exit_code
