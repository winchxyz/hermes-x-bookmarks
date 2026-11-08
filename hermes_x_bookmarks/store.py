"""Bookmarks database in Hermes plugin data (``plugin_db``): items, sync runs, small settings.

No tokens or keys are ever written here (catalog rule 11).

Order: X returns bookmarks newest-bookmarked first and gives no bookmark time, so every new item
gets a growing ``seq``; ``seq DESC`` is "most recently bookmarked first".
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from collections.abc import Callable, Iterable
from typing import Any

from .reader import Item

SCHEMA_VERSION = 2  # 2: classes
RUN_SPAN = 10_000_000  # more new bookmarks than one run can ever bring

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    author_username TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    has_article INTEGER NOT NULL DEFAULT 0,
    body_status TEXT NOT NULL DEFAULT 'full',
    data TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    removed_at TEXT
);
CREATE INDEX IF NOT EXISTS items_seq ON items(seq DESC);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    pages INTEGER NOT NULL DEFAULT 0,
    fetched INTEGER NOT NULL DEFAULT 0,
    new INTEGER NOT NULL DEFAULT 0,
    stop_reason TEXT NOT NULL DEFAULT '',
    cost TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS classes (
    item_id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    text_hash TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    category TEXT NOT NULL,
    suggested_category TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    priority INTEGER NOT NULL,
    why_saved TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS classes_category ON classes(category);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def open_db() -> sqlite3.Connection:
    """The plugin's database inside the active Hermes profile."""
    from plugins.plugin_storage import plugin_db

    from . import PLUGIN_NAME

    return plugin_db(PLUGIN_NAME)


class Store:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self._positions: dict[int, int] = {}
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"bookmarks database is from a newer plugin (schema {version})")
        with self.conn:
            self.conn.executescript(SCHEMA)
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # settings -----------------------------------------------------------------------------
    def get_meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                              "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # items --------------------------------------------------------------------------------
    def count(self, *, include_removed: bool = False) -> int:
        where = "" if include_removed else " WHERE removed_at IS NULL"
        return int(self.conn.execute("SELECT COUNT(*) FROM items" + where).fetchone()[0])

    def known_ids(self, ids: Iterable[str]) -> set[str]:
        ids = list(ids)
        if not ids:
            return set()
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(f"SELECT id FROM items WHERE id IN ({marks})", ids)
        return {r["id"] for r in rows}

    def save_page(self, run_id: int, items: list[Item], *, seen_at: str | None = None
                  ) -> list[str]:
        """Insert new items and refresh known ones; returns the new ids.

        Call with pages in X order (newest bookmark first). ``seq = run_id * RUN_SPAN - position``
        sorts a later run above an earlier one and, inside a run, the page order.
        """
        seen = seen_at or now_iso()
        known = self.known_ids(i.id for i in items)
        new = [i for i in items if i.id not in known]
        with self.conn:
            for item in new:
                self._positions[run_id] = self._positions.get(run_id, 0) + 1
                seq = run_id * RUN_SPAN - self._positions[run_id]
                self.conn.execute(
                    "INSERT INTO items(id, seq, author_username, created_at, has_article, "
                    "body_status, data, first_seen_at, last_seen_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (item.id, seq, item.author_username, item.created_at,
                     int(bool(item.article_title)), item.body_status, _dumps(item), seen, seen))
                known.add(item.id)
            new_ids = {i.id for i in new}
            for item in items:
                if item.id not in new_ids:
                    self.conn.execute(
                        "UPDATE items SET data = ?, body_status = ?, has_article = ?, "
                        "last_seen_at = ?, removed_at = NULL WHERE id = ?",
                        (_dumps(item), item.body_status, int(bool(item.article_title)), seen,
                         item.id))
        return [i.id for i in new]

    def get(self, item_id: str) -> Item | None:
        row = self.conn.execute("SELECT data FROM items WHERE id = ?", (item_id,)).fetchone()
        return Item.from_dict(json.loads(row["data"])) if row else None

    def list_items(self, *, limit: int = 20, offset: int = 0, include_removed: bool = False,
                   category: str | None = None) -> list[Item]:
        where, args = [], []
        if not include_removed:
            where.append("i.removed_at IS NULL")
        if category:
            where.append("lower(c.category) = lower(?)")
            args.append(category)
        sql = ("SELECT i.data FROM items i LEFT JOIN classes c ON c.item_id = i.id "
               + (("WHERE " + " AND ".join(where) + " ") if where else "")
               + "ORDER BY i.seq DESC LIMIT ? OFFSET ?")
        rows = self.conn.execute(sql, (*args, limit, offset))
        return [Item.from_dict(json.loads(r["data"])) for r in rows]

    # labels -------------------------------------------------------------------------------
    def unclassified(self, schema_version: int, hasher: Callable[[Item], str], *,
                     limit: int | None = None) -> list[Item]:
        """Items with no label, an older schema or changed text, most recent bookmark first."""
        rows = self.conn.execute(
            "SELECT i.data, c.text_hash, c.schema_version FROM items i "
            "LEFT JOIN classes c ON c.item_id = i.id WHERE i.removed_at IS NULL "
            "ORDER BY i.seq DESC")
        out: list[Item] = []
        for r in rows:
            item = Item.from_dict(json.loads(r["data"]))
            if r["text_hash"] is not None and r["schema_version"] == schema_version \
                    and r["text_hash"] == hasher(item):
                continue
            out.append(item)
            if limit is not None and len(out) >= limit:
                break
        return out

    def count_unclassified(self, schema_version: int) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM items i LEFT JOIN classes c ON c.item_id = i.id "
            "WHERE i.removed_at IS NULL AND (c.item_id IS NULL OR c.schema_version != ?)",
            (schema_version,)).fetchone()[0])

    def save_label(self, item_id: str, text_hash: str, schema_version: int, label: Any,
                   model: str = "") -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO classes(item_id, text_hash, schema_version, category, "
                "suggested_category, tags, kind, summary, priority, why_saved, model, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(item_id) DO UPDATE SET "
                "text_hash = excluded.text_hash, schema_version = excluded.schema_version, "
                "category = excluded.category, suggested_category = excluded.suggested_category, "
                "tags = excluded.tags, kind = excluded.kind, summary = excluded.summary, "
                "priority = excluded.priority, why_saved = excluded.why_saved, "
                "model = excluded.model, created_at = excluded.created_at",
                (item_id, text_hash, schema_version, label.category, label.suggested_category,
                 json.dumps(label.tags, ensure_ascii=False), label.kind, label.summary,
                 label.priority, label.why_saved, model, now_iso()))

    def label(self, item_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM classes WHERE item_id = ?", (item_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["tags"] = json.loads(d["tags"] or "[]")
        return d

    def category_counts(self) -> list[tuple[str, int]]:
        rows = self.conn.execute(
            "SELECT c.category, COUNT(*) AS n FROM classes c JOIN items i ON i.id = c.item_id "
            "WHERE i.removed_at IS NULL GROUP BY c.category ORDER BY n DESC, c.category")
        return [(r["category"], int(r["n"])) for r in rows]

    def llm_totals(self) -> dict[str, Any]:
        tot = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "llm_cost_usd": 0.0}
        for r in self.conn.execute("SELECT cost FROM runs WHERE kind = 'classify'"):
            c = json.loads(r["cost"] or "{}")
            for k in tot:
                tot[k] += c.get(k) or 0
        return tot

    def stats(self) -> dict[str, int]:
        row = self.conn.execute(
            "SELECT COUNT(*) AS total, SUM(has_article) AS articles, "
            "SUM(body_status = 'thread_part') AS thread_parts, "
            "SUM(body_status IN ('article_missing', 'card_only')) AS partial "
            "FROM items WHERE removed_at IS NULL").fetchone()
        return {k: int(row[k] or 0) for k in ("total", "articles", "thread_parts", "partial")}

    # runs ---------------------------------------------------------------------------------
    def start_run(self, kind: str) -> int:
        with self.conn:
            cur = self.conn.execute("INSERT INTO runs(kind, started_at) VALUES(?, ?)",
                                    (kind, now_iso()))
        return int(cur.lastrowid)

    def update_run(self, run_id: int, **fields: Any) -> None:
        allowed = {"status", "pages", "fetched", "new", "stop_reason", "cost", "error",
                   "finished_at"}
        cols = {k: (json.dumps(v) if k == "cost" else v) for k, v in fields.items()
                if k in allowed}
        if not cols:
            return
        sets = ", ".join(f"{k} = ?" for k in cols)
        with self.conn:
            self.conn.execute(f"UPDATE runs SET {sets} WHERE id = ?", (*cols.values(), run_id))

    def finish_run(self, run_id: int, status: str, **fields: Any) -> None:
        self.update_run(run_id, status=status, finished_at=now_iso(), **fields)
        self._positions.pop(run_id, None)

    def last_runs(self, n: int = 5) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (n,))
        out = []
        for r in rows:
            d = dict(r)
            d["cost"] = json.loads(d.get("cost") or "{}")
            out.append(d)
        return out


def _dumps(item: Item) -> str:
    return json.dumps(item.to_dict(), ensure_ascii=False, separators=(",", ":"))
