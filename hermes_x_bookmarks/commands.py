"""``/xbm sync | status | list`` in a Hermes chat, and the same text for ``hermes xbm``.

Each command returns plain text lines. Nothing here prints a token or a key.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from . import auth
from .reader import Item
from .store import Store, open_db
from .xapi import XApi

USAGE = ("Usage: /xbm sync [full] | /xbm status | /xbm list [N]\n"
         "  sync    pull new bookmarks from X (full: re-read all of them)\n"
         "  status  how many are stored, last syncs and their X API cost\n"
         "  list    the N most recent bookmarks (default 10)")

ApiFactory = Callable[[dict[str, Any]], XApi]
DbFactory = Callable[[], sqlite3.Connection]


def config_of(ctx: Any, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    getter = getattr(ctx, "get_config", None) if ctx is not None else None
    cfg = {k: getter(k) for k in ("auth_backend", "xurl_app")} if getter else {}
    cfg.update({k: v for k, v in (overrides or {}).items() if v})
    return cfg


def default_api(cfg: dict[str, Any]) -> XApi:
    return XApi(auth.make_transport(cfg))


def do_sync(api: XApi, store: Store, *, full: bool = False, max_pages: int | None = None,
            log: Callable[[str], None] | None = None) -> list[str]:
    from .sync import sync

    return sync(api, store, full=full, max_pages=max_pages, log=log).lines()


def do_status(store: Store) -> list[str]:
    st = store.stats()
    who = store.get_meta("x_username")
    out = [f"Stored bookmarks: {st['total']}" + (f" (X account @{who})" if who else ""),
           f"  X Articles: {st['articles']}; thread posts: {st['thread_parts']}; "
           f"partial bodies: {st['partial']}"]
    runs = store.last_runs(5)
    if not runs:
        out.append("No sync yet. Run /xbm sync.")
        return out
    out.append("Last syncs:")
    for r in runs:
        cost = r.get("cost") or {}
        line = (f"  {r['started_at']} {r['kind']}: {r['status']}, {r['new']} new / "
                f"{r['fetched']} read, {r['pages']} page(s), ~${cost.get('usd_estimate', 0):.3f}")
        if r.get("error"):
            line += f" ({r['error']})"
        out.append(line)
    return out


def _one_line(item: Item, width: int = 90) -> str:
    if item.article_title:
        head = f"[Article] {item.article_title}"
    else:
        head = " ".join(item.text.split())
    if len(head) > width:
        head = head[: width - 1].rstrip() + "…"
    return head


def do_list(store: Store, n: int = 10) -> list[str]:
    items = store.list_items(limit=max(1, min(n, 100)))
    if not items:
        return ["No bookmarks stored yet. Run /xbm sync."]
    out = []
    for k, it in enumerate(items, 1):
        who = f"@{it.author_username}" if it.author_username else "?"
        out.append(f"#{k} {who} {it.created_at[:10]}  {_one_line(it)}")
        out.append(f"    {it.url}")
    return out


def run(words: list[str], *, ctx: Any = None, api_factory: ApiFactory | None = None,
        db_factory: DbFactory | None = None, overrides: dict[str, Any] | None = None,
        log: Callable[[str], None] | None = None, max_pages: int | None = None) -> list[str]:
    """Run one subcommand given as words (``["sync", "full"]``)."""
    cmd = words[0].lower() if words else ""
    if cmd not in ("sync", "status", "list"):
        return [USAGE]
    conn = (db_factory or open_db)()
    try:
        store = Store(conn)
        if cmd == "status":
            return do_status(store)
        if cmd == "list":
            n = int(words[1]) if len(words) > 1 and words[1].isdigit() else 10
            return do_list(store, n)
        api = (api_factory or default_api)(config_of(ctx, overrides))
        full = any(w.lower() == "full" for w in words[1:])
        return do_sync(api, store, full=full, max_pages=max_pages, log=log)
    except auth.AuthUnavailable as exc:
        return [f"X sign-in unavailable: {exc}"]
    finally:
        conn.close()


def make_slash_handler(ctx: Any = None, *, api_factory: ApiFactory | None = None,
                       db_factory: DbFactory | None = None) -> Callable[..., str]:
    def handler(raw_args: str = "", **_session: Any) -> str:
        return "\n".join(run((raw_args or "").split(), ctx=ctx, api_factory=api_factory,
                             db_factory=db_factory))

    return handler
