"""Local export: Desktop finder, board.html safety, Markdown, /xbm export."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from conftest import FakeCtx

from hermes_x_bookmarks import commands, desktop, export_local
from hermes_x_bookmarks.classify import Label
from hermes_x_bookmarks.reader import Item
from hermes_x_bookmarks.store import Store

EVIL = '</script><script>alert(1)</script><!-- &gt; & "quote"'


def filled_store():
    store = Store(sqlite3.connect(":memory:"))
    run = store.start_run("full")
    items = [
        Item(id="3", url="https://x.com/a/status/3", author_username="a", created_at="2026-11-03",
             text=EVIL + " https://t.co/xyz",
             media=[{"type": "photo", "url": "javascript:alert(1)"}],
             links=[{"url": "javascript:alert(2)"}, {"url": "https://example.com/ok"}]),
        Item(id="2", url="https://x.com/b/status/2", author_username="b", created_at="2026-11-02",
             text="An article body", article_title="Big [guide] *bold*",
             media=[{"type": "photo", "url": "https://pbs.twimg.com/media/x.jpg"}]),
        Item(id="1", url="https://x.com/c/status/1", author_username="c", text="unsorted one"),
    ]
    store.save_page(run, items)
    store.save_label("3", "h", 3, Label("Crypto & web3", ["defi"], "read", "evil summary", 1))
    store.save_label("2", "h", 3, Label("AI & agents", ["ai"], "try", "guide summary", 2))
    store.set_meta("x_username", "me")
    return store


def board_data(html_text: str) -> dict:
    m = re.search(r'<script type="application/json" id="xbm-data">(.*?)</script>', html_text, re.S)
    return json.loads(m.group(1))


def test_board_is_self_contained_and_post_text_cannot_escape(tmp_path):
    res = export_local.export(filled_store(), export_dir=str(tmp_path / "out"))
    page = res.board.read_text(encoding="utf-8")
    assert page.count("</script>") == 2 and "alert(1)</script>" not in page
    assert "<!--" not in page.split('id="xbm-data">')[1].split("</script>")[0]
    assert "src=\"http" not in page and "<link" not in page  # no external scripts or styles
    data = board_data(page)
    assert data["owner"] == "me" and len(data["cards"]) == 3
    evil = data["cards"][0]
    assert evil["text"].startswith("</script><script>") and "t.co" not in evil["text"]
    assert "> &" in evil["text"]  # entities decoded for display, inserted with textContent
    assert evil["image"] == "" and evil["links"] == ["https://example.com/ok"]
    assert data["cards"][1]["image"].startswith("https://pbs.twimg.com/")
    assert data["cards"][2]["category"] == export_local.UNSORTED
    assert "textContent" in page and "innerHTML" not in page


def test_markdown_grouped_and_escaped(tmp_path):
    res = export_local.export(filled_store(), export_dir=str(tmp_path))
    md = res.markdown.read_text(encoding="utf-8")
    assert md.startswith("# X Bookmarks of @me")
    assert md.index("## AI & agents") < md.index("## Unsorted")
    assert r"Big \[guide\] \*bold\*" in md and "[post](https://x.com/b/status/2)" in md
    assert "**[p1 · read]**" in md and "`defi`" in md


def test_export_rewrites_atomically(tmp_path):
    store = filled_store()
    export_local.export(store, export_dir=str(tmp_path))
    export_local.export(store, export_dir=str(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["board.html", "bookmarks.md"]


def test_desktop_dir_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
    assert desktop.desktop_dir("linux") == tmp_path  # no Desktop folder: home
    (tmp_path / "Desktop").mkdir()
    assert desktop.desktop_dir("linux") == tmp_path / "Desktop"
    assert desktop.desktop_dir("darwin") == tmp_path / "Desktop"
    monkeypatch.setattr(desktop, "_windows_known_folder", lambda: tmp_path / "OneDrive")
    (tmp_path / "OneDrive").mkdir()
    assert desktop.desktop_dir("win32") == tmp_path / "OneDrive"


def test_default_folder_is_on_the_desktop(tmp_path, monkeypatch):
    monkeypatch.setattr(export_local, "desktop_dir", lambda: tmp_path)
    assert export_local.export_folder() == tmp_path / "X Bookmarks"


def test_slash_export(tmp_path):
    store = filled_store()
    conn = store.conn

    class Keep:
        def __getattr__(self, name):
            return getattr(conn, name)

        def __setattr__(self, name, value):
            setattr(conn, name, value)

        def __enter__(self):
            return conn.__enter__()

        def __exit__(self, *exc):
            return conn.__exit__(*exc)

        def close(self):
            pass

    ctx = FakeCtx({"export_dir": str(tmp_path / "exp")})
    out = commands.make_slash_handler(ctx, db_factory=Keep)("export")
    assert "Exported 3 bookmarks" in out and "board.html" in out
    assert "not sorted yet" in out
    assert (tmp_path / "exp" / "board.html").exists()
