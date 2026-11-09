"""``/xbm sync | classify | status | list`` in a Hermes chat, and the same text for ``hermes xbm``.

Each command returns plain text lines. Nothing here prints a token or a key.
"""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from typing import Any

from . import auth
from .reader import Item
from .store import Store, open_db
from .xapi import XApi

USAGE = ("Usage: /xbm sync [full] | classify [N|all] | export | status | list [N] [category]"
         " | about\n"
         "  sync      pull new bookmarks from X (full: re-read all of them)\n"
         "  classify  sort unsorted bookmarks with your model (default 20 at a time)\n"
         "  export    write bookmarks.md and board.html to 'X Bookmarks' on your Desktop\n"
         "  status    counts, categories, last runs, X API and model cost\n"
         "  list      the N most recent bookmarks (default 10), optionally of one category\n"
         "  about     what you build and follow, so sorting can judge priority "
         "(about <text> | about clear)")

CHAT_CLASSIFY_DEFAULT = 20
CHAT_CLASSIFY_MAX = 100  # a chat command blocks its turn; bigger runs belong in the terminal

TCO = re.compile(r"https?://t\.co/\S*")

ApiFactory = Callable[[dict[str, Any]], XApi]
DbFactory = Callable[[], sqlite3.Connection]
CONFIG_KEYS = ("auth_backend", "xurl_app", "categories", "classify_language",
               "about_me", "export_dir")


def config_of(ctx: Any, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    getter = getattr(ctx, "get_config", None) if ctx is not None else None
    cfg = {k: getter(k) for k in CONFIG_KEYS} if getter else {}
    cfg.update({k: v for k, v in (overrides or {}).items() if v})
    return cfg


def default_api(cfg: dict[str, Any]) -> XApi:
    return XApi(auth.make_transport(cfg))


def do_sync(api: XApi, store: Store, *, full: bool = False, max_pages: int | None = None,
            log: Callable[[str], None] | None = None) -> list[str]:
    from .sync import sync

    return sync(api, store, full=full, max_pages=max_pages, log=log).lines()


def do_classify(llm: Any, store: Store, cfg: dict[str, Any], *, limit: int | None,
                log: Callable[[str], None] | None = None) -> list[str]:
    from . import classify

    if llm is None:
        return ["No model access here: run this inside Hermes (/xbm classify or hermes xbm "
                "classify)."]
    if store.count() == 0:
        return ["No bookmarks stored yet. Run /xbm sync first."]
    res = classify.classify(llm, store, limit=limit,
                            categories=classify.categories_from(cfg.get("categories")),
                            language=str(cfg.get("classify_language") or "English"),
                            about_me=str(cfg.get("about_me") or ""),
                            own_username=store.get_meta("x_username"), log=log)
    return res.lines()


def _run_line(r: dict[str, Any]) -> str:
    cost = r.get("cost") or {}
    if r["kind"] == "classify":
        line = (f"  {r['started_at']} classify: {r['status']}, {r['new']} sorted / "
                f"{r['fetched']} tried, {cost.get('calls', 0)} call(s), "
                f"{cost.get('input_tokens', 0) + cost.get('output_tokens', 0)} tokens")
        if cost.get("llm_cost_usd"):
            line += f", ~${cost['llm_cost_usd']:.4f}"
    else:
        line = (f"  {r['started_at']} {r['kind']} sync: {r['status']}, {r['new']} new / "
                f"{r['fetched']} read, {r['pages']} page(s), ~${cost.get('usd_estimate', 0):.3f}")
    if r.get("error"):
        line += f" ({r['error'][:200]})"
    return line


def do_status(store: Store) -> list[str]:
    from .classify import SCHEMA_VERSION

    st = store.stats()
    who = store.get_meta("x_username")
    out = [f"Stored bookmarks: {st['total']}" + (f" (X account @{who})" if who else ""),
           f"  X Articles: {st['articles']}; thread posts: {st['thread_parts']}; "
           f"partial bodies: {st['partial']}"]
    cats = store.category_counts()
    if cats:
        unsorted = store.count_unclassified(SCHEMA_VERSION)
        out.append(f"Sorted: {st['total'] - unsorted}, unsorted: {unsorted}. "
                   + ", ".join(f"{c} {n}" for c, n in cats))
        tot = store.llm_totals()
        out.append(f"  Model use so far: {tot['calls']} call(s), {tot['input_tokens']} tokens in, "
                   f"{tot['output_tokens']} out"
                   + (f", about ${tot['llm_cost_usd']:.4f}" if tot["llm_cost_usd"] else "") + ".")
    runs = store.last_runs(5)
    if not runs:
        out.append("No sync yet. Run /xbm sync.")
        return out
    out.append("Last runs:")
    out.extend(_run_line(r) for r in runs)
    return out


def _one_line(item: Item, width: int = 90) -> str:
    if item.article_title:
        head = f"[Article] {item.article_title}"
    else:
        head = " ".join(TCO.sub("", item.text).split()) or "(media only)"
    if len(head) > width:
        head = head[: width - 1].rstrip() + "…"
    return head


def _match_category(store: Store, wanted: str) -> str | None:
    w = wanted.strip().lower()
    names = [c for c, _ in store.category_counts()]
    for c in names:
        if c.lower() == w:
            return c
    starts = [c for c in names if c.lower().startswith(w)]
    return starts[0] if len(starts) == 1 else None


def do_list(store: Store, n: int = 10, category: str = "") -> list[str]:
    cat = None
    if category:
        cat = _match_category(store, category)
        if not cat:
            known = ", ".join(c for c, _ in store.category_counts()) or "none yet"
            return [f"No category matches {category!r}. Categories: {known}."]
    items = store.list_items(limit=max(1, min(n, 100)), category=cat)
    if not items:
        return ["No bookmarks stored yet. Run /xbm sync."]
    out = []
    for k, it in enumerate(items, 1):
        who = f"@{it.author_username}" if it.author_username else "?"
        out.append(f"#{k} {who} {it.created_at[:10]}  {_one_line(it)}")
        lab = store.label(it.id)
        if lab:
            out.append(f"    {lab['category']} · {lab['kind']} · p{lab['priority']} · "
                       f"{lab['summary']}")
        out.append(f"    {it.url}")
    return out


def do_export(store: Store, cfg: dict[str, Any]) -> list[str]:
    from . import export_local

    if store.count() == 0:
        return ["No bookmarks stored yet. Run /xbm sync first."]
    try:
        res = export_local.export(store, export_dir=str(cfg.get("export_dir") or "") or None)
    except OSError as exc:
        return [f"Export failed: {exc}"]
    from .classify import SCHEMA_VERSION

    lines = res.lines()
    unsorted = store.count_unclassified(SCHEMA_VERSION)
    if unsorted:
        lines.append(f"{unsorted} bookmark(s) are not sorted yet (column 'Unsorted'); "
                     "/xbm classify sorts them.")
    return lines


def do_about(ctx: Any, rest: list[str]) -> list[str]:
    from .classify import ABOUT_MAX

    current = str(config_of(ctx).get("about_me") or "")
    if not rest:
        if not current:
            return ["No 'about me' set. Example: /xbm about I build Hermes Agent plugins and "
                    "follow AI agents and crypto security."]
        return [f"About you (used to judge priority): {current}"]
    setter = getattr(ctx, "set_config", None) if ctx is not None else None
    if setter is None:
        return ["Cannot save settings here: run it inside Hermes."]
    text = "" if [w.lower() for w in rest] == ["clear"] else " ".join(" ".join(rest).split())
    setter("about_me", text[:ABOUT_MAX])
    if not text:
        return ["'About me' cleared."]
    note = f" (cut to {ABOUT_MAX} characters)" if len(text) > ABOUT_MAX else ""
    return [f"Saved{note}. Sorting runs from now on use it."]


def _llm_of(ctx: Any) -> Any:
    try:
        return getattr(ctx, "llm", None) if ctx is not None else None
    except Exception:  # noqa: BLE001 - outside Hermes the property may fail to import
        return None


def run(words: list[str], *, ctx: Any = None, api_factory: ApiFactory | None = None,
        db_factory: DbFactory | None = None, overrides: dict[str, Any] | None = None,
        log: Callable[[str], None] | None = None, max_pages: int | None = None,
        classify_cap: int | None = CHAT_CLASSIFY_MAX) -> list[str]:
    """Run one subcommand given as words (``["sync", "full"]``, ``["list", "5", "ai"]``)."""
    cmd = words[0].lower() if words else ""
    if cmd not in ("sync", "classify", "export", "status", "list", "about"):
        return [USAGE]
    if cmd == "about":
        return do_about(ctx, words[1:])
    conn = (db_factory or open_db)()
    try:
        store = Store(conn)
        if cmd == "status":
            return do_status(store)
        rest = words[1:]
        if cmd == "list":
            n = int(rest[0]) if rest and rest[0].isdigit() else 10
            cat = " ".join(rest[1:] if rest and rest[0].isdigit() else rest)
            return do_list(store, n, cat)
        cfg = config_of(ctx, overrides)
        if cmd == "export":
            return do_export(store, cfg)
        if cmd == "classify":
            limit: int | None = CHAT_CLASSIFY_DEFAULT
            if rest and rest[0].isdigit():
                limit = max(1, int(rest[0]))
            elif rest and rest[0].lower() == "all":
                limit = None
            if classify_cap is not None:
                limit = min(limit or classify_cap, classify_cap)
            return do_classify(_llm_of(ctx), store, cfg, limit=limit, log=log)
        api = (api_factory or default_api)(cfg)
        full = any(w.lower() == "full" for w in rest)
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
