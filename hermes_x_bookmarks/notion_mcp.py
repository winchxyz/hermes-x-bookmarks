"""Notion export through Hermes' own Notion connector (the hosted Notion MCP server).

No token and no Notion app of your own: Hermes signs in to Notion once with
``hermes mcp install notion`` (OAuth in the browser), and this plugin calls that server through
``ctx.call_mcp``. Hermes only lets a plugin call an MCP server the user granted it::

    plugins:
      entries:
        hermes-x-bookmarks:
          mcp_allowlist: ["notion"]

The database, its boards and the pages are the same as on the token route (``notion.py``), and
both routes share the export state, so switching between them re-sends nothing.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from typing import Any

from .export_local import UNSORTED, card
from .notion import (
    BODY_BLOCKS,
    COLORS,
    GONE,
    IMAGE_EXT,
    KINDS,
    TARGET,
    NotionResult,
    content_hash,
    page_id_from,
    page_properties,
)
from .obsidian import full_text
from .reader import Item
from .store import Store

SERVER = "notion"
BATCH = 25                  # pages per notion-create-pages call
BATCH_CHARS = 150_000       # and at most this much Markdown per call
PAGE_CHARS = 40_000         # Markdown per page
TIMEOUT = 120.0
SEED_TAGS = 30
UUID = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", re.I)
COLLECTION = re.compile(r"collection://([0-9a-f-]{32,36})", re.I)
NOTION_URL = re.compile(r"https://(?:www\.)?(?:app\.)?notion\.(?:so|com)/[^\s\"'<>)\\]*", re.I)
GONE_HINTS = ("archived", "trash", "not found", "could not find", "404", "deleted")

CallMcp = Callable[..., dict[str, Any]]


class McpError(RuntimeError):
    """A failed tool call; ``unavailable`` when the connector itself is not usable."""

    def __init__(self, message: str, *, unavailable: bool = False) -> None:
        super().__init__(message)
        self.unavailable = unavailable


def setup_hint(plugin_id: str = "hermes-x-bookmarks") -> str:
    return ("Notion through Hermes: run `hermes mcp install notion` once (it signs you in to "
            "Notion in the browser), allow this plugin to use it with "
            f"`plugins.entries.{plugin_id}.mcp_allowlist: [\"notion\"]` in config.yaml, then run "
            "`/xbm export notion` in a Hermes chat.")


class Connector:
    """Calls one Notion MCP tool and returns the parsed result, or raises McpError."""

    def __init__(self, call_mcp: CallMcp, server: str = SERVER) -> None:
        self.call_mcp, self.server = call_mcp, server
        self.calls = 0

    def call(self, tool: str, arguments: dict[str, Any], timeout: float = TIMEOUT) -> Any:
        self.calls += 1
        try:
            env = self.call_mcp(self.server, tool, arguments, timeout=timeout)
        except PermissionError:
            raise McpError("This plugin may not use your Notion connector yet.",
                           unavailable=True) from None
        if not isinstance(env, dict):
            raise McpError(f"{tool}: unexpected answer from the connector")
        if not env.get("ok"):
            msg = str(env.get("error") or "unknown error")
            low = msg.lower()
            unavailable = any(s in low for s in (
                "not connected", "unknown mcp server", "not configured", "no mcp server",
                "not found in config", "unauthorized", "401", "login", "re-auth"))
            raise McpError(f"{tool}: {msg[:300]}", unavailable=unavailable)
        structured = env.get("structuredContent")
        result = env.get("result")
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                pass
        return {"result": result, "structured": structured}


def _text(answer: Any) -> str:
    try:
        return json.dumps(answer, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(answer)


def _dashed(value: str) -> str:
    return page_id_from(value) if value else ""


# markdown ----------------------------------------------------------------------------------
_ESCAPE = re.compile(r"([\\`*_\[\]<>$~|#^])")
_LINE_START = re.compile(r"^(\s*)([-+=]|\d+[.)])", re.M)


def escape(text: str) -> str:
    """Plain text as Notion-flavored Markdown: no headings, lists, math, tags or links."""
    out = _ESCAPE.sub(r"\\\1", text or "")
    return _LINE_START.sub(lambda m: m.group(1) + "\\" + m.group(2), out)


def paragraph(text: str) -> str:
    lines = [ln.rstrip() for ln in escape(text.strip()).split("\n")]
    return "\\\n".join(ln for ln in lines if ln.strip())


def page_markdown(item: Item, c: dict[str, Any]) -> str:
    parts: list[str] = []
    if c["summary"]:
        parts.append(f"<callout icon=\"\U0001f4cc\">\n{paragraph(c['summary'])}\n</callout>")
    size, cut = 0, False
    for k, p in enumerate(p for p in re.split(r"\n\s*\n", full_text(item)) if p.strip()):
        block = paragraph(p)
        if k >= BODY_BLOCKS or size + len(block) > PAGE_CHARS:
            cut = True
            break
        parts.append(block)
        size += len(block)
    if cut and c["url"]:
        parts.append(f"[Continued on X]({c['url']})")
    if c["quoted"]:
        who = f"@{c['quotedAuthor']}: " if c["quotedAuthor"] else ""
        parts.append(f"<quote>\n{paragraph(who + c['quoted'])}\n</quote>")
    if c["image"] and c["image"].split("?")[0].lower().endswith(IMAGE_EXT):
        parts.append(f"![]({c['image']})")
    if c["url"]:
        parts.append(f"<bookmark source=\"{c['url']}\"></bookmark>")
    return "\n\n".join(parts)


def mcp_properties(c: dict[str, Any]) -> dict[str, Any]:
    """The REST properties of notion.py in the connector's SQLite form."""
    rest = page_properties(c)
    text = lambda key: "".join(r["text"]["content"]  # noqa: E731
                               for r in rest[key].get("rich_text") or rest[key].get("title") or [])
    sel = lambda key: (rest[key]["select"] or {}).get("name")  # noqa: E731
    props: dict[str, Any] = {
        "Name": text("Name"),
        "Category": sel("Category"),
        "Kind": sel("Kind"),
        "Priority": sel("Priority"),
        "Tags": [t["name"] for t in rest["Tags"]["multi_select"]],
        "Summary": text("Summary"),
        "Why saved": text("Why saved"),
        "Author": text("Author"),
        "userDefined:URL": rest["URL"]["url"],
        "Article": "__YES__" if rest["Article"]["checkbox"] else "__NO__",
        "Post ID": text("Post ID"),
    }
    if "Posted" in rest:
        props["date:Posted:start"] = rest["Posted"]["date"]["start"]
        props["date:Posted:is_datetime"] = 0
    return props


def _q(name: str) -> str:
    return name.replace("'", "’").replace('"', "”")


def schema_ddl(categories: list[str], tags: list[str]) -> str:
    cats = list(dict.fromkeys([*categories, "Other", UNSORTED]))
    cat_opts = ", ".join(f"'{_q(c)}':{COLORS[k % len(COLORS)]}" for k, c in enumerate(cats))
    tag_opts = ", ".join(f"'{_q(t)}':gray" for t in (tags or ["misc"]))
    kinds = ", ".join(f"'{k}':default" for k in KINDS)
    return ("CREATE TABLE (\"Name\" TITLE, "
            f"\"Category\" SELECT({cat_opts}), "
            "\"Status\" STATUS('Not started':gray:to_do, 'In progress':blue:in_progress, "
            "'Done':green:complete), "
            f"\"Kind\" SELECT({kinds}), "
            "\"Priority\" SELECT('P1':red, 'P2':yellow, 'P3':gray), "
            f"\"Tags\" MULTI_SELECT({tag_opts}), "
            "\"Summary\" RICH_TEXT, \"Why saved\" RICH_TEXT, \"Author\" RICH_TEXT, "
            "\"Posted\" DATE, \"URL\" URL, \"Article\" CHECKBOX, \"Post ID\" RICH_TEXT)")


# database -------------------------------------------------------------------------------------
def _gone(exc: McpError) -> bool:
    low = str(exc).lower()
    return any(h in low for h in GONE_HINTS)


def ensure_database(conn: Connector, store: Store, parent: str, categories: list[str],
                    tags: list[str], res: NotionResult) -> str:
    """The data source id to write rows into; creates database and boards when needed."""
    ds = store.get_meta("notion_data_source_id")
    if ds and store.get_meta("notion_parent") == parent:
        try:
            conn.call("notion-fetch", {"id": f"collection://{ds}"}, timeout=60)
            res.url = store.get_meta("notion_database_url")
            return ds
        except McpError as exc:
            if exc.unavailable or not _gone(exc):
                raise
    answer = conn.call("notion-create-database", {
        "parent": {"type": "page_id", "page_id": parent},
        "title": "X Bookmarks",
        "description": "Your X bookmarks, sorted by Hermes (hermes-x-bookmarks).",
        "schema": schema_ddl(categories, tags),
    })
    text = _text(answer)
    m = COLLECTION.search(text)
    if not m:
        raise McpError("notion-create-database: no data source id in the answer")
    ds = _dashed(m.group(1))
    db_id, url = "", ""
    for u in NOTION_URL.findall(text):
        ids = [_dashed(x) for x in UUID.findall(u)]
        if ids and ids[-1] not in (ds, parent):
            db_id, url = ids[-1], u
            break
    if not db_id:
        for x in UUID.findall(text):
            d = _dashed(x)
            if d not in (ds, parent):
                db_id = d
                break
    res.url = url or (f"https://www.notion.so/{db_id.replace('-', '')}" if db_id else "")
    res.new_database = True
    store.set_meta("notion_parent", parent)
    store.set_meta("notion_database_id", db_id)
    store.set_meta("notion_data_source_id", ds)
    store.set_meta("notion_database_url", res.url)
    if not db_id:
        res.notes.append("Boards were not created. In Notion: + Add view → Board → Group by "
                         "Category.")
        return ds
    for name, configure in (("By category", 'GROUP BY "Category" HIDE EMPTY'),
                            ("By status", 'GROUP BY "Status" BY OPTION')):
        try:
            conn.call("notion-create-view", {"database_id": db_id, "data_source_id": ds,
                                             "name": name, "type": "board",
                                             "configure": configure}, timeout=60)
        except McpError as exc:
            res.notes.append(f"Board '{name}' was not created ({str(exc)[:120]}). In Notion: "
                             "+ Add view → Board.")
    return ds


def created_ids(answer: Any, exclude: set[str]) -> list[str]:
    """Page ids from a notion-create-pages answer, in order."""
    for part in (answer.get("structured"), answer.get("result")):
        pages = part.get("pages") if isinstance(part, dict) else None
        if isinstance(pages, list):
            ids = []
            for p in pages:
                raw = (p.get("id") or p.get("url") or "") if isinstance(p, dict) else str(p)
                ids.append(_dashed(str(raw)))
            if all(ids):
                return ids
    seen: list[str] = []
    for x in UUID.findall(_text(answer)):
        d = _dashed(x)
        if d and d not in exclude and d not in seen:
            seen.append(d)
    return seen


# export ---------------------------------------------------------------------------------------
def export(store: Store, *, parent: str, categories: list[str], call_mcp: CallMcp,
           limit: int | None = None, log: Callable[[str], None] | None = None,
           server: str = SERVER) -> NotionResult:
    res = NotionResult()
    page = page_id_from(parent)
    if not page:
        res.errors.append("Set notion_page to the URL of the Notion page the database goes under "
                          "(`/xbm export notion <page URL>` saves it).")
        return res
    conn = Connector(call_mcp, server)
    rows = [(item, card(item, label)) for item, label in store.labelled_items()]
    tags = [t for t, _ in Counter(t for _, c in rows for t in c["tags"]).most_common(SEED_TAGS)]
    try:
        ds = ensure_database(conn, store, page, categories, tags, res)
    except McpError as exc:
        res.unavailable = exc.unavailable
        res.errors.append(str(exc))
        if exc.unavailable:
            res.errors.append(setup_hint())
        return res
    target = f"{TARGET}:{ds}"
    done = store.export_map(target)
    exclude = {ds, page, _dashed(store.get_meta("notion_database_id") or "")}
    batch: list[tuple[Item, dict[str, Any], str, str]] = []
    batch_size = BATCH
    work = 0

    def flush() -> None:
        nonlocal batch_size
        if not batch:
            return
        pages = [{"properties": props, "content": md} for _, props, md, _ in batch]
        answer = conn.call("notion-create-pages", {
            "parent": {"type": "data_source_id", "data_source_id": ds},
            "pages": pages, "allow_async": False})
        ids = created_ids(answer, exclude)
        if len(ids) != len(batch):
            if len(batch) == 1:
                ids = ids[:1] or [""]
            else:
                ids = [""] * len(batch)
                batch_size = 1
                res.notes.append("Notion did not return the new page ids; pages created in this "
                                 "run will not be updated by later exports.")
        for (it, _, _, h), pid in zip(batch, ids, strict=True):
            store.save_export(target, it.id, pid, h)
            res.created += 1
        batch.clear()

    try:
        for item, c in rows:
            h = content_hash(page_properties(c))
            known = done.get(item.id)
            if known and known[1] == GONE:
                res.skipped_deleted += 1
                continue
            if known and known[1] == h:
                res.unchanged += 1
                continue
            if limit is not None and work >= limit:
                res.left += 1
                continue
            work += 1
            props = mcp_properties(c)
            if known and known[0]:
                try:
                    conn.call("notion-update-page", {"page_id": known[0],
                                                     "command": "update_properties",
                                                     "properties": props}, timeout=60)
                    store.save_export(target, item.id, known[0], h)
                    res.updated += 1
                except McpError as exc:
                    if exc.unavailable:
                        raise
                    if _gone(exc):
                        store.save_export(target, item.id, known[0], GONE)
                        res.skipped_deleted += 1
                    else:
                        res.errors.append(f"post {item.id}: {exc}")
                continue
            if known:  # created earlier without a page id: cannot update it
                store.save_export(target, item.id, "", h)
                res.unchanged += 1
                continue
            md = page_markdown(item, c)
            if batch and (len(batch) >= batch_size
                          or sum(len(b[2]) for b in batch) + len(md) > BATCH_CHARS):
                flush()
            batch.append((item, props, md, h))
            if log and work % 50 == 0:
                log(f"Notion: {work} page(s) written...")
            if len(res.errors) >= 5:
                break
        flush()
    except McpError as exc:
        res.left += len(batch)
        res.errors.append(str(exc))
        if exc.unavailable:
            res.errors.append(setup_hint())
    return res
