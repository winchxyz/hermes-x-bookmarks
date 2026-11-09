"""Notion export: a database "X Bookmarks" under one page you share with your Notion connection.

* Token: ``XBM_NOTION_TOKEN`` in the Hermes profile's ``.env`` (an internal connection token,
  or a personal access token), read through Hermes' secret scope. Never stored or printed.
* Parent: the ``notion_page`` setting, a page URL or id. Share that page with the connection.
* First export creates the database, a "By category" board and a "By status" board.
* One page per bookmark, keyed by the post id. Re-exports update only what the plugin owns
  (name, category, tags, summary, ...). ``Status`` is yours: set on create, never touched again.
  A page you delete in Notion is not re-created.

Requests: Notion-Version 2026-03-11, at most ~2.5 per second, Retry-After honoured on 429/529.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .export_local import UNSORTED, card
from .obsidian import full_text
from .reader import Item
from .store import Store

API = "https://api.notion.com/v1"
VERSION = "2026-03-11"
TOKEN_ENV = "XBM_NOTION_TOKEN"
TARGET = "notion"
MIN_INTERVAL = 0.4          # seconds between requests: 2.5 per second
MAX_TRIES = 5
RICH_MAX = 2000             # characters per rich text item
BODY_BLOCKS = 90            # paragraphs of post text per page (Notion allows 100 children)
GONE = "gone"               # hash value for a page the user deleted in Notion
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
KINDS = ("read", "try", "task", "post-idea", "reference", "skill-candidate")
PAGE_ID = re.compile(r"([0-9a-f]{32})(?:[?#].*)?$", re.I)
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
COLORS = ("blue", "green", "orange", "purple", "pink", "yellow", "red", "brown", "gray")

Send = Callable[[str, str, Any], tuple[int, dict[str, str], Any]]


class NotionError(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"Notion {status} {code}: {message}")
        self.status, self.code = status, code


@dataclass
class NotionResult:
    url: str = ""
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_deleted: int = 0
    left: int = 0
    new_database: bool = False
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [f"Notion: {self.created} new page(s), {self.updated} updated, "
               f"{self.unchanged} unchanged"
               + (f", {self.skipped_deleted} deleted by you and left out"
                  if self.skipped_deleted else "") + "."]
        if self.url:
            out.append(f"  Database: {self.url}")
        if self.left:
            out.append(f"  {self.left} more to go: run the export again (or `hermes xbm export "
                       "notion` in a terminal for all at once).")
        out += [f"  {n}" for n in self.notes]
        out += [f"  {e}" for e in self.errors[:5]]
        return out


def page_id_from(value: str) -> str:
    """A Notion page id (dashed UUID) from a page URL or a bare id; "" if none."""
    v = (value or "").strip()
    m = UUID.search(v)
    if m:
        return m.group(0).lower()
    m = PAGE_ID.search(v.replace("-", ""))
    if not m:
        return ""
    h = m.group(1).lower()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def httpx_send(token: str, timeout: float = 30.0) -> Send:
    import httpx

    client = httpx.Client(timeout=timeout, follow_redirects=False, headers={
        "Authorization": f"Bearer {token}", "Notion-Version": VERSION,
        "Content-Type": "application/json"})

    def send(method: str, path: str, body: Any) -> tuple[int, dict[str, str], Any]:
        try:
            r = client.request(method, API + path, json=body)
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Notion request failed ({type(exc).__name__})") from None
        try:
            data = r.json()
        except ValueError:
            data = {}
        return r.status_code, dict(r.headers), data

    return send


class NotionApi:
    def __init__(self, send: Send, *, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.send, self.sleep, self.clock = send, sleep, clock
        self.calls = 0
        self._last = -MIN_INTERVAL

    def call(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        for attempt in range(MAX_TRIES):
            wait = MIN_INTERVAL - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
            self._last = self.clock()
            self.calls += 1
            status, headers, data = self.send(method, path, body)
            data = data if isinstance(data, dict) else {}
            if status in (429, 529, 502, 503) and data.get("code") != "public_api_request_blocked" \
                    and attempt < MAX_TRIES - 1:
                retry = next((v for k, v in headers.items() if k.lower() == "retry-after"), "")
                self.sleep(min(float(retry) if retry.replace(".", "", 1).isdigit()
                               else 2.0 ** attempt, 60.0))
                continue
            if status >= 400:
                raise NotionError(status, str(data.get("code") or ""),
                                  str(data.get("message") or "")[:300])
            return data
        raise NotionError(429, "rate_limited", "still rate limited after retries")


# payloads -----------------------------------------------------------------------------------
def rich(text: str, link: str = "") -> list[dict[str, Any]]:
    """Rich text items of at most 2000 characters each (max 100 items)."""
    text = text or ""
    parts = [text[i:i + RICH_MAX] for i in range(0, len(text), RICH_MAX)][:100] or []
    out = []
    for part in parts:
        t: dict[str, Any] = {"content": part}
        if link:
            t["link"] = {"url": link}
        out.append({"type": "text", "text": t})
    return out


def _option(name: str) -> str:
    return " ".join(name.replace(",", " ").split())[:100]


def database_schema(categories: list[str]) -> dict[str, Any]:
    cats = list(dict.fromkeys([*categories, "Other", UNSORTED]))
    return {
        "Name": {"title": {}},
        "Category": {"select": {"options": [
            {"name": _option(c), "color": COLORS[k % len(COLORS)]} for k, c in enumerate(cats)]}},
        "Status": {"status": {}},
        "Kind": {"select": {"options": [{"name": k} for k in KINDS]}},
        "Priority": {"select": {"options": [{"name": "P1", "color": "red"},
                                            {"name": "P2", "color": "yellow"},
                                            {"name": "P3", "color": "gray"}]}},
        "Tags": {"multi_select": {}},
        "Summary": {"rich_text": {}},
        "Why saved": {"rich_text": {}},
        "Author": {"rich_text": {}},
        "Posted": {"date": {}},
        "URL": {"url": {}},
        "Article": {"checkbox": {}},
        "Post ID": {"rich_text": {}},
    }


def page_properties(c: dict[str, Any]) -> dict[str, Any]:
    name = c["title"] or c["summary"] or c["text"][:120] or "(media only)"
    props: dict[str, Any] = {
        "Name": {"title": rich(name[:300])},
        "Category": {"select": {"name": _option(c["category"])}},
        "Kind": {"select": {"name": c["kind"]} if c["kind"] else None},
        "Priority": {"select": {"name": f"P{c['priority']}"} if c["priority"] else None},
        "Tags": {"multi_select": [{"name": _option(t)} for t in
                                  dict.fromkeys(t for t in c["tags"] if _option(t))][:10]},
        "Summary": {"rich_text": rich(c["summary"])},
        "Why saved": {"rich_text": rich(c["why"])},
        "Author": {"rich_text": rich("@" + c["author"]) if c["author"] else []},
        "URL": {"url": c["url"] or None},
        "Article": {"checkbox": bool(c["article"])},
        "Post ID": {"rich_text": rich(c["id"])},
    }
    if len(c["date"]) == 10:
        props["Posted"] = {"date": {"start": c["date"]}}
    return props


def page_children(item: Item, c: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if c["summary"]:
        blocks.append({"type": "callout", "callout": {
            "rich_text": rich(c["summary"]), "icon": {"type": "emoji", "emoji": "\U0001f4cc"}}})
    text = full_text(item)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    for p in paras[:BODY_BLOCKS]:
        blocks.append({"type": "paragraph", "paragraph": {"rich_text": rich(p)[:100]}})
    if len(paras) > BODY_BLOCKS:
        blocks.append({"type": "paragraph", "paragraph": {
            "rich_text": rich("Continued on X.", c["url"])}})
    if c["quoted"]:
        who = f"@{c['quotedAuthor']}: " if c["quotedAuthor"] else ""
        blocks.append({"type": "quote", "quote": {"rich_text": rich(who + c["quoted"])}})
    if c["image"] and c["image"].split("?")[0].lower().endswith(IMAGE_EXT):
        blocks.append({"type": "image", "image": {"type": "external",
                                                  "external": {"url": c["image"]}}})
    if c["url"]:
        blocks.append({"type": "bookmark", "bookmark": {"url": c["url"]}})
    return blocks[:100]


def content_hash(props: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(props, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()[:32]


# database -------------------------------------------------------------------------------------
def _explain(exc: NotionError) -> str:
    if exc.status == 401:
        return ("Notion rejected the token. Check XBM_NOTION_TOKEN in the Hermes .env "
                "(copy it again from notion.so/profile/integrations).")
    if exc.status in (403, 404):
        return ("Notion cannot see that page. Open it, click ••• → Connections and add your "
                "connection, then export again.")
    return str(exc)


def ensure_database(api: NotionApi, store: Store, parent: str, categories: list[str],
                    res: NotionResult) -> str:
    """The data source id to write rows into; creates database and views when needed."""
    ds = store.get_meta("notion_data_source_id")
    if ds and store.get_meta("notion_parent") == parent:
        try:
            data = api.call("GET", f"/data_sources/{ds}")
            if not data.get("in_trash"):
                # a new category needs no schema change: Notion adds unknown select options
                res.url = store.get_meta("notion_database_url")
                return ds
        except NotionError as exc:
            if exc.status not in (404, 400):
                raise
    db = api.call("POST", "/databases", {
        "parent": {"type": "page_id", "page_id": parent},
        "title": rich("X Bookmarks"),
        "icon": {"type": "emoji", "emoji": "\U0001f516"},
        "initial_data_source": {"properties": database_schema(categories)},
    })
    db_id = db["id"]
    ds = db["data_sources"][0]["id"]
    res.url = str(db.get("url") or "")
    res.new_database = True
    store.set_meta("notion_parent", parent)
    store.set_meta("notion_database_id", db_id)
    store.set_meta("notion_data_source_id", ds)
    store.set_meta("notion_database_url", res.url)
    try:
        props = api.call("GET", f"/data_sources/{ds}").get("properties") or {}
        cat_id = (props.get("Category") or {}).get("id")
        status_id = (props.get("Status") or {}).get("id")
        if cat_id:
            api.call("POST", "/views", {
                "database_id": db_id, "data_source_id": ds, "name": "By category",
                "type": "board", "configuration": {"type": "board", "group_by": {
                    "type": "select", "property_id": cat_id, "sort": {"type": "manual"},
                    "hide_empty_groups": True}}})
        if status_id:
            api.call("POST", "/views", {
                "database_id": db_id, "data_source_id": ds, "name": "By status",
                "type": "board", "configuration": {"type": "board", "group_by": {
                    "type": "status", "property_id": status_id, "group_by": "option",
                    "sort": {"type": "manual"}}}})
    except (NotionError, KeyError) as exc:
        res.notes.append("Boards were not created (" + str(exc)[:120] + "). In Notion: "
                         "+ Add view → Board → Group by Category.")
    return ds


# export ---------------------------------------------------------------------------------------
def export(store: Store, *, parent: str, categories: list[str], send: Send | None = None,
           token: str = "", limit: int | None = None, api: NotionApi | None = None,
           log: Callable[[str], None] | None = None) -> NotionResult:
    res = NotionResult()
    page = page_id_from(parent)
    if not page:
        res.errors.append("Set notion_page to the URL of a Notion page you shared with your "
                          "connection (Plugins settings, or `/xbm notion <page URL>`).")
        return res
    if api is None:
        if send is None:
            if not token:
                res.errors.append(f"{TOKEN_ENV} is not set in the Hermes profile's .env. "
                                  "Create a connection at notion.so/profile/integrations.")
                return res
            send = httpx_send(token)
        api = NotionApi(send)
    try:
        ds = ensure_database(api, store, page, categories, res)
    except NotionError as exc:
        res.errors.append(_explain(exc))
        return res
    target = f"{TARGET}:{ds}"
    done = store.export_map(target)
    work = 0
    for item, label in store.labelled_items():
        c = card(item, label)
        props = page_properties(c)
        h = content_hash(props)
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
        try:
            if known:
                try:
                    api.call("PATCH", f"/pages/{known[0]}", {"properties": props})
                    res.updated += 1
                except NotionError as exc:
                    if exc.status == 404 or "archived" in str(exc).lower() \
                            or "trash" in str(exc).lower():
                        store.save_export(target, item.id, known[0], GONE)
                        res.skipped_deleted += 1
                        continue
                    raise
            else:
                body = {"parent": {"type": "data_source_id", "data_source_id": ds},
                        "properties": props, "children": page_children(item, c)}
                try:
                    created = api.call("POST", "/pages", body)
                except NotionError as exc:
                    if exc.status != 400:
                        raise
                    body.pop("children")  # a block Notion refused (an image URL, say)
                    created = api.call("POST", "/pages", body)
                res.created += 1
                known = (created["id"], "")
            store.save_export(target, item.id, known[0], h)
        except NotionError as exc:
            res.errors.append(f"post {item.id}: {_explain(exc)}")
            if exc.status in (401, 403, 429) or len(res.errors) >= 5:
                res.left += 1
                break
        if log and work % 50 == 0:
            log(f"Notion: {work} page(s) written...")
    return res
