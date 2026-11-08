"""Store and sync: first sync stores everything, the next one fetches only new bookmarks."""
from __future__ import annotations

import sqlite3

import pytest
from conftest import FakeCtx, FakeTransport

from hermes_x_bookmarks import cli, commands, register
from hermes_x_bookmarks.reader import Item
from hermes_x_bookmarks.store import Store
from hermes_x_bookmarks.sync import STOP_AFTER_KNOWN, sync
from hermes_x_bookmarks.xapi import XApi


class FakeX:
    """Bookmarks newest first; pages by max_results with tokens 'o<offset>'."""

    def __init__(self, ids):
        self.ids = list(ids)
        self.rate_limit_after: int | None = None
        self.requests = 0

    def post(self, pid):
        return {"id": pid, "text": f"post {pid}", "author_id": "u1", "conversation_id": pid,
                "created_at": "2026-11-01T00:00:00.000Z"}

    def route(self, path, q):
        if path == "/2/users/me":
            return 200, {"data": {"id": "42", "username": "me"}}, {}
        assert path == "/2/users/42/bookmarks", path
        self.requests += 1
        if self.rate_limit_after is not None and self.requests > self.rate_limit_after:
            return 429, {"title": "Too Many Requests"}, {"x-rate-limit-reset": "1999999999"}
        size = int(q["max_results"])
        start = int((q.get("pagination_token") or "o0")[1:])
        chunk = self.ids[start:start + size]
        meta = {"result_count": len(chunk)}
        if start + size < len(self.ids):
            meta["next_token"] = f"o{start + size}"
        return 200, {"data": [self.post(i) for i in chunk],
                     "includes": {"users": [{"id": "u1", "username": "alice", "name": "A"}]},
                     "meta": meta}, {}


def make(ids):
    x = FakeX(ids)
    transport = FakeTransport(x.route)
    return x, transport, XApi(transport)


@pytest.fixture
def store():
    return Store(sqlite3.connect(":memory:"))


def ids_desc(n, top=1000):
    return [str(top - k) for k in range(n)]


def test_first_sync_is_full_then_incremental_stops_at_known(store):
    x, t, api = make(ids_desc(200))
    r = sync(api, store)
    assert (r.kind, r.status, r.stop_reason, r.new, r.pages) == ("full", "ok", "end", 200, 3)
    assert {q["max_results"] for p, q in t.calls if p.endswith("/bookmarks")} == {"90"}
    assert [i.id for i in store.list_items(limit=3)] == ["1000", "999", "998"]

    x.ids = ["1003", "1002", "1001"] + x.ids  # three new bookmarks on top
    t.calls.clear()
    r = sync(api, store)
    assert (r.kind, r.stop_reason, r.new, r.pages) == ("incremental", "known", 3, 1)
    bookmark_calls = [q for p, q in t.calls if p.endswith("/bookmarks")]
    assert len(bookmark_calls) == 1 and bookmark_calls[0]["max_results"] == "20"
    assert not any(p == "/2/users/me" for p, _ in t.calls)  # user id is remembered
    assert [i.id for i in store.list_items(limit=5)] == ["1003", "1002", "1001", "1000", "999"]
    assert store.count() == 203


def test_rebookmarked_old_post_on_top_does_not_hide_new_ones(store):
    x, _, api = make(ids_desc(50))
    sync(api, store)
    x.ids = ["990", "2001", "2000"] + [i for i in x.ids if i != "990"]
    r = sync(api, store)
    assert r.new == 2 and r.stop_reason == "known"
    assert STOP_AFTER_KNOWN > 1


def test_rate_limit_keeps_pages_already_stored(store):
    x, _, api = make(ids_desc(200))
    x.rate_limit_after = 1
    r = sync(api, store)
    assert r.status == "rate_limited" and r.reset_at == 1999999999 and r.new == 90
    assert store.count() == 90
    assert "rate limit" in "\n".join(r.lines())
    run = store.last_runs(1)[0]
    assert run["status"] == "rate_limited" and run["new"] == 90 and run["cost"]["requests"] >= 1


def test_max_pages_reported(store):
    _, _, api = make(ids_desc(200))
    r = sync(api, store, max_pages=1)
    assert r.stop_reason == "max_pages" and r.new == 90


def test_full_sync_refreshes_known_items(store):
    x, _, api = make(ids_desc(30))
    sync(api, store)
    x.post = lambda pid: {"id": pid, "text": f"edited {pid}", "author_id": "u1",
                          "conversation_id": pid}
    r = sync(api, store, full=True)
    assert r.kind == "full" and r.new == 0 and r.fetched == 30
    assert store.get("1000").text == "edited 1000"


def test_store_never_holds_secrets(store, monkeypatch):
    from conftest import MARKER_TOKEN

    _, _, api = make(ids_desc(5))
    sync(api, store)
    dump = "\n".join(store.conn.iterdump())
    assert MARKER_TOKEN not in dump and "oauth_" not in dump


def test_store_rejects_newer_schema():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError):
        Store(conn)


def test_item_survives_store(store):
    run = store.start_run("full")
    item = Item(id="1", url="https://x.com/a/status/1", text="hi", links=[{"url": "u"}])
    assert store.save_page(run, [item]) == ["1"]
    assert store.save_page(run, [item]) == []
    assert store.get("1") == item and store.get("nope") is None


# ---- commands: /xbm and hermes xbm ---------------------------------------------------------

class Shared:
    """One in-memory database that survives the close() each command does."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")

    def factory(self):
        conn = self.conn

        class NoClose:
            def __getattr__(self, name):
                return getattr(conn, name)

            def __setattr__(self, name, value):
                setattr(conn, name, value)

            def close(self):
                pass

            def __enter__(self):
                return conn.__enter__()

            def __exit__(self, *exc):
                return conn.__exit__(*exc)

        return NoClose()


def test_slash_command_sync_status_list():
    db = Shared()
    _, _, api = make(ids_desc(12))
    ctx = FakeCtx()
    register(ctx)
    assert "xbm" in ctx.commands and "xbm" in ctx.cli
    handler = commands.make_slash_handler(ctx, api_factory=lambda cfg: api,
                                          db_factory=db.factory)
    assert "Usage" in handler("")
    assert "No sync yet" in handler("status")
    out = handler("sync")
    assert "12 new" in out and "reached the end" in out
    status = handler("status", session_id="s1")
    assert "Stored bookmarks: 12 (X account @me)" in status and "full: ok" in status
    listing = handler("list 2")
    assert listing.startswith("#1 @alice") and "#2 @alice" in listing and "#3" not in listing
    assert "https://x.com/alice/status/1000" in listing


def test_cli_sync_and_list(capsys):
    import argparse

    db = Shared()
    _, _, api = make(ids_desc(3))
    handler = cli.make_handler(api_factory=lambda cfg: api, db_factory=db.factory)
    ns = argparse.Namespace(xbm_cmd="sync", full=False, max_pages=None, backend=None,
                            xurl_app=None)
    assert handler(ns) == 0
    assert handler(argparse.Namespace(xbm_cmd="list", limit=1)) == 0
    out = capsys.readouterr().out
    assert "3 new" in out and "#1 @alice" in out and "#2" not in out


def test_cli_parser_has_new_subcommands():
    import argparse

    parser = argparse.ArgumentParser()
    cli.setup(parser)
    ns = parser.parse_args(["sync", "--full", "--max-pages", "2"])
    assert ns.xbm_cmd == "sync" and ns.full and ns.max_pages == 2
    assert parser.parse_args(["list", "--limit", "5"]).limit == 5


def test_list_drops_tco_links_and_cli_survives_cp1252(capsys, monkeypatch):
    import io
    import sys

    db = Shared()
    run = Store(db.factory()).start_run("full")
    Store(db.factory()).save_page(run, [Item(id="1", url="u", author_username="a",
                                             text="Nice ✨ https://t.co/abc tail")])
    lines = commands.do_list(Store(db.factory()), 1)
    assert "t.co" not in lines[0] and "Nice ✨ tail" in lines[0]

    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))
    cli.say(lines[0])
    sys.stdout.flush()
    assert b"Nice ? tail" in raw.getvalue()
