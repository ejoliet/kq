from __future__ import annotations

import pytest

from conftest import FIXTURES, dump_cmd
from kq.cli import main
from kq.store import open_ro


def capture(path):
    assert main(["run", "--", *dump_cmd(path)]) == 0


def current(paths, handle="r001"):
    conn = open_ro(paths)
    try:
        row = conn.execute(
            "SELECT kind, source_format, envelope_key, n_rows, n_cols, summary "
            "FROM kq.artifacts WHERE handle = ? AND is_current",
            [handle],
        ).fetchone()
        return dict(
            zip(
                ["kind", "source_format", "envelope_key", "n_rows", "n_cols", "summary"],
                row,
                strict=True,
            )
        )
    finally:
        conn.close()


def test_envelope_unwrap_items(kq_env, capfd):
    capture(FIXTURES / "pods.json")
    capfd.readouterr()
    a = current(kq_env)
    assert (a["kind"], a["source_format"], a["envelope_key"]) == ("table", "json", "items")
    assert a["n_rows"] == 60
    assert a["summary"].startswith("items[] ")
    assert "kind=List" in a["summary"]


def test_envelope_unwrap_contents_keeps_scalars(kq_env, capfd):
    capture(FIXTURES / "s3_list.json")
    capfd.readouterr()
    a = current(kq_env)
    assert a["envelope_key"] == "Contents"
    assert a["n_rows"] == 80
    assert a["summary"].startswith("Contents[] ")
    assert "KeyCount=80" in a["summary"] or "IsTruncated=False" in a["summary"]


def test_two_arrays_are_not_unwrapped(kq_env, capfd):
    capture(FIXTURES / "two_arrays.json")
    capfd.readouterr()
    a = current(kq_env)
    assert a["envelope_key"] is None
    assert a["kind"] == "table"
    assert a["n_rows"] == 1


def test_ndjson(kq_env, capfd):
    capture(FIXTURES / "events.ndjson")
    capfd.readouterr()
    a = current(kq_env)
    assert (a["kind"], a["source_format"], a["n_rows"]) == ("table", "ndjson", 200)


@pytest.mark.parametrize("name,fmt", [("catalog.csv", "csv"), ("catalog.tsv", "tsv")])
def test_delimited(kq_env, capfd, name, fmt):
    capture(FIXTURES / name)
    capfd.readouterr()
    a = current(kq_env)
    assert (a["kind"], a["source_format"]) == ("table", fmt)
    assert (a["n_rows"], a["n_cols"]) == (300, 3)


def test_ragged_csv_falls_through_to_text(kq_env, capfd):
    capture(FIXTURES / "ragged.csv")
    capfd.readouterr()
    assert current(kq_env)["kind"] == "text"


def test_plain_log_is_text_not_one_column_table(kq_env, capfd):
    """DuckDB's sniffer reports delimiter ',' for plain text; the rule must not fall for it."""
    capture(FIXTURES / "plain.log")
    capfd.readouterr()
    a = current(kq_env)
    assert (a["kind"], a["source_format"], a["n_rows"], a["n_cols"]) == ("text", "text", 300, 2)


def test_text_summary_counts_levels(kq_env, capfd):
    capture(FIXTURES / "mixed.log")
    capfd.readouterr()
    summary = current(kq_env)["summary"]
    assert summary.startswith('first: "2026-10-08 INFO starting"')
    assert "ERROR," in summary and summary.endswith("WARN")


def test_non_utf8_becomes_text_with_replacement_chars(kq_env, capfd, non_utf8_file):
    capture(non_utf8_file)
    capfd.readouterr()
    a = current(kq_env)
    assert a["kind"] == "text"
    conn = open_ro(kq_env)
    try:
        joined = "".join(r[0] for r in conn.execute("SELECT line FROM r001").fetchall())
    finally:
        conn.close()
    assert "�" in joined


def test_handle_line_format(kq_env, capfd):
    capture(FIXTURES / "pods.json")
    out, _ = capfd.readouterr()
    handle, kind, shape, summary = out.strip().split("  ", 3)
    assert handle == "r001"
    assert kind == "table"
    assert shape == "60 rows × 3 cols"
    assert summary and len(summary) <= 120
