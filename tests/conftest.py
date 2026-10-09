from __future__ import annotations

import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def dump_cmd(path: Path) -> list[str]:
    """A wrapped command that prints a fixture verbatim. Never a real CLI."""
    return [
        sys.executable,
        "-c",
        "import sys; sys.stdout.buffer.write(open(sys.argv[1], 'rb').read())",
        str(path),
    ]


@pytest.fixture
def kq_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KQ_HOME", str(tmp_path / "kqhome"))
    monkeypatch.setenv("KQ_SESSION", "test-session")
    monkeypatch.setenv("KQ_THRESHOLD_TOKENS", "50")
    monkeypatch.delenv("KQ_MAX_BYTES", raising=False)
    monkeypatch.delenv("KQ_LOCK_TIMEOUT_S", raising=False)
    monkeypatch.delenv("KQ_OTLP_ENDPOINT", raising=False)
    from kq.session import resolve_session

    return resolve_session(None)


@pytest.fixture
def non_utf8_file(tmp_path):
    p = tmp_path / "non_utf8.bin"
    p.write_bytes(b"first line\n\xff\xfe not utf-8 \x81\nlast line\n" * 40)
    return p
