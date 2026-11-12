"""Runs.cost must always read back as a dict.

0.3.0 digests wrote cost double-encoded (digest.py passed json.dumps(usage)
into Store.finish_run, which serialises it again), and ``hermes xbm status``
then crashed with AttributeError in commands._run_line. Regression tests for
the write guard and for healing legacy rows on read.
"""
import json
import sqlite3

from hermes_x_bookmarks import commands
from hermes_x_bookmarks.store import Store

USAGE = {"calls": 1, "input_tokens": 10, "output_tokens": 5, "llm_cost_usd": 0.0}


def _store() -> Store:
    return Store(sqlite3.connect(":memory:"))


def _legacy_row(store: Store, kind: str = "digest") -> None:
    """Write a run row exactly the way 0.3.0 wrote digest costs."""
    run = store.start_run(kind)
    with store.conn:
        store.conn.execute(
            "UPDATE runs SET status='ok', cost=? WHERE id=?",
            (json.dumps(json.dumps(USAGE)), run),
        )


def test_finish_run_accepts_dict_and_pre_serialised_string():
    store = _store()
    for cost in (USAGE, json.dumps(USAGE)):  # classify/sync shape, 0.3.0 digest shape
        run = store.start_run("digest")
        store.finish_run(run, "ok", cost=cost)
    raw = [r["cost"] for r in store.conn.execute("SELECT cost FROM runs ORDER BY id")]
    assert raw
    for value in raw:  # stored exactly once, never double-encoded
        assert isinstance(json.loads(value), dict)


def test_last_runs_heals_legacy_double_encoded_cost():
    store = _store()
    _legacy_row(store)
    assert store.last_runs(1)[0]["cost"] == USAGE


def test_status_renders_legacy_digest_rows():
    store = _store()
    _legacy_row(store)
    lines = commands.do_status(store)  # 0.3.0: AttributeError here
    assert any("digest" in line for line in lines)


def test_llm_totals_heals_legacy_and_skips_unrecoverable():
    store = _store()
    _legacy_row(store, kind="classify")
    assert store.llm_totals()["calls"] == USAGE["calls"]  # healed, counted
    run = store.start_run("classify")
    with store.conn:
        store.conn.execute(
            "UPDATE runs SET status='ok', cost=? WHERE id=?", ('"not an object"', run))
    totals = store.llm_totals()  # unrecoverable row: skipped, no crash
    assert totals["calls"] == USAGE["calls"]
