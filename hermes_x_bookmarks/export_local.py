"""Local export, no accounts needed: ``X Bookmarks/bookmarks.md`` and ``X Bookmarks/board.html``.

The folder goes on the user's real Desktop unless the ``export_dir`` setting names another one.
Both files are rewritten on every export (atomic replace). ``board.html`` is one self-contained
file: data inline as JSON, no network except post images loaded from X's own image host.
"""
from __future__ import annotations

import datetime as _dt
import html
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .desktop import desktop_dir
from .reader import Item
from .store import Store

FOLDER = "X Bookmarks"
UNSORTED = "Unsorted"
TEXT_CLIP = 2000      # characters of body text per card
TCO = re.compile(r"https?://t\.co/\S*")


@dataclass
class ExportResult:
    folder: Path
    markdown: Path
    board: Path
    count: int

    def lines(self) -> list[str]:
        return [f"Exported {self.count} bookmarks to {self.folder}",
                f"  {self.board.name}: open it in a browser (filters, columns, search)",
                f"  {self.markdown.name}: the same list as Markdown, grouped by category"]


def export_folder(export_dir: str | None = None) -> Path:
    base = Path(os.path.expandvars(os.path.expanduser(export_dir))) if export_dir \
        else desktop_dir() / FOLDER
    base.mkdir(parents=True, exist_ok=True)
    return base


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _clean(text: str) -> str:
    # unescape again for items stored before the reader did it
    return " ".join(TCO.sub("", html.unescape(text or "")).split())


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def card(item: Item, label: dict[str, Any] | None) -> dict[str, Any]:
    """The JSON one board card needs. Only http(s) URLs survive."""
    def safe(u: str) -> str:
        return u if u.startswith(("https://", "http://")) else ""

    image = next((safe(m.get("url", "")) for m in item.media
                  if m.get("type") == "photo" and safe(m.get("url", ""))), "")
    quoted = item.quoted or {}
    lab = label or {}
    return {
        "id": item.id, "url": safe(item.url), "author": item.author_username,
        "name": item.author_name, "date": item.created_at[:10],
        "title": html.unescape(item.article_title), "text": _clip(_clean(item.text), TEXT_CLIP),
        "quoted": _clip(_clean(quoted.get("article_title") or quoted.get("text") or ""), 300),
        "quotedAuthor": quoted.get("author_username", ""),
        "image": image, "links": [safe(link["url"]) for link in item.links[:3]
                                  if safe(link.get("url", ""))],
        "category": lab.get("category") or UNSORTED, "kind": lab.get("kind") or "",
        "priority": int(lab.get("priority") or 0), "summary": lab.get("summary") or "",
        "why": lab.get("why_saved") or "", "tags": lab.get("tags") or [],
        "article": bool(item.article_title), "thread": item.in_thread,
    }


def build_markdown(cards: list[dict[str, Any]], generated: str, owner: str = "") -> str:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in cards:
        groups[c["category"]].append(c)
    order = sorted(groups, key=lambda g: (g == UNSORTED, -len(groups[g]), g))
    out = [f"# X Bookmarks{f' of @{owner}' if owner else ''}", "",
           f"{len(cards)} bookmarks, exported {generated}. Article bodies come from the X API "
           "as plain text (no headings or links). Made by hermes-x-bookmarks.", ""]
    out.append("Categories: " + ", ".join(f"[{g}](#{_anchor(g)}) ({len(groups[g])})"
                                          for g in order))
    for g in order:
        items = sorted(groups[g], key=lambda c: (c["priority"] or 9))
        out += ["", f"## {g}", ""]
        for c in items:
            head = c["title"] or c["summary"] or _clip(c["text"], 140) or "(media only)"
            badge = " · ".join(x for x in (f"p{c['priority']}" if c["priority"] else "",
                                           c["kind"]) if x)
            line = f"- {'**[' + badge + ']** ' if badge else ''}{_md(head)}"
            line += f" — @{c['author']}, {c['date']} · [post]({c['url']})"
            out.append(line)
            if c["title"] and c["summary"]:
                out.append(f"  {_md(c['summary'])}")
            if c["tags"]:
                out.append("  " + " ".join(f"`{t}`" for t in c["tags"]))
    return "\n".join(out) + "\n"


def _anchor(s: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", s.lower()).strip().replace(" ", "-")


def _md(s: str) -> str:
    return re.sub(r"([\\`*_\[\]<>|])", r"\\\1", s)


def build_html(cards: list[dict[str, Any]], generated: str, owner: str = "") -> str:
    from .board_template import TEMPLATE

    data = json.dumps({"cards": cards, "generated": generated, "owner": owner},
                      ensure_ascii=False, separators=(",", ":"))
    # Inside <script type="application/json"> no "<" may appear raw, so nothing can close the tag
    # or open a comment; < is the same character to JSON.parse.
    data = data.replace("<", "\\u003c")
    return TEMPLATE.replace("__XBM_DATA__", data)


def export(store: Store, *, export_dir: str | None = None,
           now: _dt.datetime | None = None) -> ExportResult:
    folder = export_folder(export_dir)
    generated = (now or _dt.datetime.now()).strftime("%Y-%m-%d %H:%M")
    owner = store.get_meta("x_username")
    cards = [card(i, lab) for i, lab in store.labelled_items()]
    md, board = folder / "bookmarks.md", folder / "board.html"
    _write(md, build_markdown(cards, generated, owner))
    _write(board, build_html(cards, generated, owner))
    return ExportResult(folder=folder, markdown=md, board=board, count=len(cards))
