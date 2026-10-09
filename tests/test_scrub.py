from __future__ import annotations

import secrets as fake
import sys

import pytest

from kq.cli import main
from kq.scrub import scrub_bytes, scrub_text
from kq.store import open_ro


@pytest.mark.parametrize("kind,sample", sorted(fake.all_samples().items()))
def test_each_pattern_is_redacted(kind, sample):
    out, n = scrub_text(f"line before\n{sample}\nline after\n")
    assert n >= 1
    assert "[REDACTED:" in out
    secret_tail = sample.split()[-1].strip('"')
    assert secret_tail not in out
    assert "line before" in out and "line after" in out


@pytest.mark.parametrize("sample", fake.near_misses())
def test_near_misses_survive(sample):
    out, n = scrub_text(sample)
    assert (out, n) == (sample, 0)


def test_redaction_count_is_per_match():
    text = "\n".join([fake.github_token(), fake.github_token(), fake.aws_key_id()])
    _, n = scrub_text(text)
    assert n == 3


def test_value_only_redaction_keeps_the_key():
    out, _ = scrub_text(fake.kv_secret_line())
    assert out.startswith("password=")
    assert "hunter2" not in out


def test_scrub_preserves_non_utf8_bytes():
    data = b"\xff\xfe " + fake.github_token().encode() + b" \x81"
    out, n = scrub_bytes(data)
    assert n == 1
    assert out.startswith(b"\xff\xfe ") and out.endswith(b" \x81")


def test_nothing_secret_reaches_disk(kq_env, capfd, tmp_path):
    payload = "\n".join(list(fake.all_samples().values()) * 20)
    source = tmp_path / "leaky.log"
    source.write_text(payload + "\n")
    code = main(
        [
            "run",
            "--",
            sys.executable,
            "-c",
            "import sys; sys.stdout.write(open(sys.argv[1]).read())",
            str(source),
        ]
    )
    capfd.readouterr()
    assert code == 0

    needles = [v.splitlines()[-1] for v in fake.all_samples().values()]
    blobs = [p.read_bytes() for p in kq_env.artifacts.glob("*.parquet")]
    assert blobs
    conn = open_ro(kq_env)
    try:
        blobs.append(
            str(
                conn.execute(
                    "SELECT event_id, name, op, status, error_type, attributes FROM kq.events"
                ).fetchall()
            ).encode()
        )
        blobs.append(str(conn.execute("SELECT * FROM r001").fetchall()).encode())
        blobs.append(
            str(conn.execute("SELECT summary, producer_text FROM kq.artifacts").fetchall()).encode()
        )
        redactions = conn.execute("SELECT redactions FROM kq.artifacts").fetchone()[0]
    finally:
        conn.close()
    assert redactions > 0
    for blob in blobs:
        for needle in needles:
            assert needle.encode() not in blob


def test_argv_is_scrubbed_before_storage(kq_env, capfd):
    token = fake.github_token()
    code = main(["run", "--", sys.executable, "-c", f"print('q' * 20000)  # {token}"])
    capfd.readouterr()
    assert code == 0
    conn = open_ro(kq_env)
    try:
        producer_text = conn.execute("SELECT producer_text FROM kq.artifacts").fetchone()[0]
    finally:
        conn.close()
    assert token not in producer_text
    assert "[REDACTED:github_token]" in producer_text
