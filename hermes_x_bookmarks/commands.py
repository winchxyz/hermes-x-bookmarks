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

USAGE = ("Usage: /xbm sync [full] | classify [N|all] | export [where] | status"
         " | list [N] [category] | about\n"
         "  sync      pull new bookmarks from X (full: re-read all of them)\n"
         "  classify  sort unsorted bookmarks with your model (default 20 at a time)\n"
         "  export    write your bookmarks out; where: desktop, obsidian, notion [page URL],"
         " gdocs\n"
         "            (several allowed; default: the export_to setting, else desktop)\n"
         "  status    counts, categories, last runs, X API and model cost\n"
         "  list      the N most recent bookmarks (default 10), optionally of one category\n"
         "  about     what you build and follow, so sorting can judge priority "
         "(about <text> | about clear)")

CHAT_CLASSIFY_DEFAULT = 20
CHAT_CLASSIFY_MAX = 100  # a chat command blocks its turn; bigger runs belong in the terminal
CHAT_NOTION_MAX = 100    # Notion pages per chat export (about 40 s); the terminal has no cap
CONNECTOR_FACTOR = 3     # the Notion connector writes 25 pages per call: 300 per chat export
TARGETS = ("desktop", "obsidian", "notion", "gdocs")
TARGET_ALIASES = {"local": "desktop", "md": "desktop", "html": "desktop", "board": "desktop",
                  "google": "gdocs", "docs": "gdocs", "gdoc": "gdocs", "googledocs": "gdocs",
                  "vault": "obsidian"}

TCO = re.compile(r"https?://t\.co/\S*")

ApiFactory = Callable[[dict[str, Any]], XApi]
DbFactory = Callable[[], sqlite3.Connection]
CONFIG_KEYS = ("auth_backend", "xurl_app", "categories", "classify_language",
               "about_me", "export_dir", "export_to", "obsidian_vault", "notion_page")


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


def parse_targets(words: list[str], default: str = "") -> tuple[list[str], str, list[str]]:
    """(targets, Notion page URL if given, unknown words) from ``export`` arguments."""
    targets: list[str] = []
    page = ""
    unknown: list[str] = []
    for w in words:
        low = w.lower().strip(",")
        if "notion." in low or (len(low.replace("-", "")) == 32 and "notion" in targets):
            page = w
            if "notion" not in targets:
                targets.append("notion")
            continue
        name = TARGET_ALIASES.get(low, low)
        if name == "all":
            targets += [t for t in TARGETS if t not in targets]
        elif name in TARGETS:
            if name not in targets:
                targets.append(name)
        elif low:
            unknown.append(w)
    if not targets and not unknown:
        for w in str(default or "desktop").replace(",", " ").split():
            name = TARGET_ALIASES.get(w.lower(), w.lower())
            if name in TARGETS and name not in targets:
                targets.append(name)
    return targets or ([] if unknown else ["desktop"]), page, unknown


def export_notion(store: Store, ctx: Any, parent: str, categories: list[str], *,
                  limit: int | None, log: Callable[[str], None] | None = None) -> Any:
    """Hermes' Notion connector first; the XBM_NOTION_TOKEN route when it is not available."""
    from . import notion, notion_mcp, secrets

    call_mcp = getattr(ctx, "call_mcp", None) if ctx is not None else None
    token = secrets.get(notion.TOKEN_ENV)
    if callable(call_mcp):
        res = notion_mcp.export(store, parent=parent, categories=categories, call_mcp=call_mcp,
                                limit=None if limit is None else limit * CONNECTOR_FACTOR,
                                log=log)
        if not (res.unavailable and token):
            return res
        note = "The Notion connector is not available here, so XBM_NOTION_TOKEN was used."
    elif token:
        note = ""
    else:
        res = notion.NotionResult()
        res.errors.append(notion_mcp.setup_hint())
        res.errors.append(f"Or put a Notion connection token in the Hermes .env as "
                          f"{notion.TOKEN_ENV}.")
        return res
    res = notion.export(store, parent=parent, categories=categories, token=token, limit=limit,
                        log=log)
    if note:
        res.notes.insert(0, note)
    return res


def do_export(store: Store, cfg: dict[str, Any], words: list[str] | None = None, *,
              ctx: Any = None, notion_limit: int | None = CHAT_NOTION_MAX,
              log: Callable[[str], None] | None = None) -> list[str]:
    from .classify import SCHEMA_VERSION, categories_from

    if store.count() == 0:
        return ["No bookmarks stored yet. Run /xbm sync first."]
    targets, page, unknown = parse_targets(words or [], str(cfg.get("export_to") or ""))
    if unknown:
        return [f"Unknown export target: {' '.join(unknown)}. Use: desktop, obsidian, notion, "
                "gdocs or all."]
    lines: list[str] = []
    for target in targets:
        try:
            if target == "desktop":
                from . import export_local

                lines += export_local.export(
                    store, export_dir=str(cfg.get("export_dir") or "") or None).lines()
            elif target == "obsidian":
                from . import obsidian

                lines += obsidian.export(store, vault=str(cfg.get("obsidian_vault") or "")).lines()
            elif target == "notion":
                if page:
                    setter = getattr(ctx, "set_config", None) if ctx is not None else None
                    if setter:
                        setter("notion_page", page)
                lines += export_notion(store, ctx, page or str(cfg.get("notion_page") or ""),
                                       categories_from(cfg.get("categories")),
                                       limit=notion_limit, log=log).lines()
            elif target == "gdocs":
                from . import gdocs

                lines += gdocs.export(store).lines()
        except Exception as exc:  # noqa: BLE001 - one target failing must not stop the others
            name = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
            lines.append(f"{target} export failed: {name}")
    unsorted = store.count_unclassified(SCHEMA_VERSION)
    if unsorted:
        lines.append(f"{unsorted} bookmark(s) are not sorted yet (category 'Unsorted'); "
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
            return do_export(store, cfg, rest, ctx=ctx, log=log,
                             notion_limit=CHAT_NOTION_MAX if classify_cap is not None else None)
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
