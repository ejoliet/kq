from __future__ import annotations

import sys

from conftest import FIXTURES, dump_cmd
from kq.cli import KqError, main
from kq.store import open_ro


def artifacts(paths):
    conn = open_ro(paths)
    try:
        return conn.execute(
            "SELECT handle, version, kind, source_format, envelope_key, n_rows, n_cols, summary "
            "FROM kq.artifacts WHERE is_current ORDER BY handle"
        ).fetchall()
    finally:
        conn.close()


def test_small_output_passes_through_unchanged(kq_env, capfd):
    code = main(["run", "--", sys.executable, "-c", "print('hello')"])
    out, _ = capfd.readouterr()
    assert code == 0
    assert out == "hello\n"
    assert not kq_env.db.exists() or artifacts(kq_env) == []


def test_exit_code_is_mirrored(kq_env, capfd):
    assert main(["run", "--", sys.executable, "-c", "import sys; sys.exit(3)"]) == 3
    capfd.readouterr()


def test_exit_code_mirrored_for_large_output(kq_env, capfd):
    code = main(["run", "--", sys.executable, "-c", "import sys; print('x' * 20000); sys.exit(2)"])
    out, _ = capfd.readouterr()
    assert code == 2
    assert out.startswith("r001  text")


def test_stderr_passes_through(kq_env, capfd):
    main(["run", "--", sys.executable, "-c", "import sys; sys.stderr.write('boom\\n')"])
    out, err = capfd.readouterr()
    assert "boom" in err
    assert out == ""


def test_large_output_prints_one_handle_line(kq_env, capfd):
    code = main(["run", "--", *dump_cmd(FIXTURES / "catalog.csv")])
    out, _ = capfd.readouterr()
    assert code == 0
    assert len(out.strip().splitlines()) == 1
    assert out.startswith("r001  table  300 rows × 3 cols  ")
    assert (kq_env.artifacts / "r001.v1.parquet").exists()


def test_store_failure_falls_back_to_raw_stdout(kq_env, capfd, monkeypatch):
    def broken(*args, **kwargs):
        raise KqError("E_STORE", "store unreadable")

    monkeypatch.setattr("kq.capture.open_rw", broken)
    code = main(["run", "--", sys.executable, "-c", "import sys; print('y' * 20000); sys.exit(4)"])
    out, err = capfd.readouterr()
    assert code == 4
    assert out.startswith("y" * 100)
    assert "E_STORE" in err


def test_max_bytes_truncates_and_warns(kq_env, capfd, monkeypatch):
    monkeypatch.setenv("KQ_MAX_BYTES", "5000")
    main(["run", "--", sys.executable, "-c", "print('z' * 20000)"])
    out, err = capfd.readouterr()
    assert "E_TOO_LARGE" in err
    assert out.strip().startswith("r001  text")
    assert artifacts(kq_env)[0][-1].endswith("[truncated]")


def test_empty_output_stores_nothing(kq_env, capfd):
    code = main(["run", "--", *dump_cmd(FIXTURES / "empty.txt")])
    out, _ = capfd.readouterr()
    assert code == 0
    assert out == ""
    assert not kq_env.db.exists() or artifacts(kq_env) == []


def test_invalid_as_name_is_usage_error(kq_env, capfd):
    assert main(["run", "--as", "R1", "--", sys.executable, "-c", "print(1)"]) == 2
    _, err = capfd.readouterr()
    assert "E_USAGE" in err
