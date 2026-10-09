from __future__ import annotations

from conftest import dump_cmd
from kq.cli import main
from kq.store import open_ro


def versions(paths):
    conn = open_ro(paths)
    try:
        return conn.execute(
            "SELECT handle, version, is_current FROM kq.artifacts ORDER BY handle, version"
        ).fetchall()
    finally:
        conn.close()


def test_identical_rerun_adds_no_version(kq_env, capfd, tmp_path):
    source = tmp_path / "payload.csv"
    source.write_text("a,b\n" + "1,2\n" * 3000)
    cmd = ["run", "--", *dump_cmd(source)]

    assert main(cmd) == 0
    first, _ = capfd.readouterr()
    assert first.startswith("r001  table")

    assert main(cmd) == 0
    second, _ = capfd.readouterr()
    assert second.strip() == "unchanged since r001 v1"

    assert versions(kq_env) == [("r001", 1, True)]
    assert len(list(kq_env.artifacts.glob("*.parquet"))) == 1


def test_changed_output_creates_a_new_version(kq_env, capfd, tmp_path):
    source = tmp_path / "payload.csv"
    source.write_text("a,b\n" + "1,2\n" * 3000)
    cmd = ["run", "--as", "src", "--", *dump_cmd(source)]

    assert main(cmd) == 0
    capfd.readouterr()
    source.write_text("a,b\n" + "1,3\n" * 3000)
    assert main(cmd) == 0
    out, _ = capfd.readouterr()
    assert out.startswith("src  table")

    assert versions(kq_env) == [("src", 1, False), ("src", 2, True)]
    assert {p.name for p in kq_env.artifacts.glob("*.parquet")} == {
        "src.v1.parquet",
        "src.v2.parquet",
    }


def test_dedup_matches_the_target_handle_even_from_another_command(kq_env, capfd, tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    body = "a,b\n" + "1,2\n" * 3000
    a.write_text(body)
    b.write_text(body)

    assert main(["run", "--as", "src", "--", *dump_cmd(a)]) == 0
    capfd.readouterr()
    assert main(["run", "--as", "src", "--", *dump_cmd(b)]) == 0
    out, _ = capfd.readouterr()
    assert out.strip() == "unchanged since src v1"


def test_byte_difference_is_a_new_version(kq_env, capfd, tmp_path):
    source = tmp_path / "payload.log"
    source.write_text("line\n" * 3000)
    cmd = ["run", "--as", "src", "--", *dump_cmd(source)]
    assert main(cmd) == 0
    capfd.readouterr()
    source.write_text("line\n" * 2999 + "line \n")
    assert main(cmd) == 0
    out, _ = capfd.readouterr()
    assert "unchanged" not in out
    assert versions(kq_env)[-1] == ("src", 2, True)
