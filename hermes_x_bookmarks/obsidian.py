"""Obsidian export: one note per bookmark in ``<vault>/X Bookmarks/``, plus a Bases view.

A note is created once with a body; later exports only refresh the plugin's own front matter keys
(category, tags, summary, ...). The body, ``status`` and any key you add stay as you left them.
Notes are found again by their ``tweet_id`` key, so renaming or moving a note inside the folder
is fine. Deleting a note brings it back on the next export (delete the bookmark on X instead).

The vault is the ``obsidian_vault`` setting, or else the vault Obsidian itself lists as open in its
``obsidian.json`` (read-only; the file holds vault paths, nothing secret).
"""
from __future__ import annotations

import datetime as _dt
import html
import json
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .export_local import TCO, UNSORTED, card
from .reader import Item
from .store import Store

FOLDER = "X Bookmarks"
BASE_FILE = "X Bookmarks.base"
OWNED = ("tweet_id", "url", "author", "posted", "category", "tags", "kind", "priority",
         "summary", "why_saved", "article", "exported")
HEAD_LINES = 60  # front matter lines read when indexing existing notes
TWEET_ID = re.compile(r'^tweet_id:\s*["\']?(\d+)', re.M)
KEY_LINE = re.compile(r"^([A-Za-z_][\w-]*)\s*:")
BAD_NAME = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')

BASE_TEXT = """filters:
  and:
    - file.inFolder("X Bookmarks")
views:
  - type: table
    name: All bookmarks
    order:
      - file.name
      - category
      - kind
      - priority
      - status
      - author
      - posted
    sort:
      - property: priority
        direction: ASC
  - type: cards
    name: To read
    filters:
      and:
        - 'status != "done"'
    order:
      - file.name
      - category
      - summary
"""


@dataclass
class ObsidianResult:
    folder: Path
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [f"Obsidian: {self.created} new note(s), {self.updated} updated, "
               f"{self.unchanged} unchanged in {self.folder}"]
        if self.created + self.updated + self.unchanged:
            out.append(f"  Open '{BASE_FILE}' in that folder for a table of all bookmarks.")
        out += [f"  {e}" for e in self.errors[:5]]
        return out


class VaultNotFound(RuntimeError):
    pass


# vault ----------------------------------------------------------------------------------------
def obsidian_config_path(platform: str | None = None) -> Path:
    plat = platform or sys.platform
    if plat == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") \
            / "obsidian" / "obsidian.json"
    if plat == "darwin":
        return Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "obsidian" / "obsidian.json"


def vault_from_obsidian(config_file: Path) -> Path | None:
    """The open vault (else the most recently used one) that Obsidian lists."""
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    vaults = [v for v in (data.get("vaults") or {}).values()
              if isinstance(v, dict) and v.get("path")]
    if not vaults:
        return None
    best = sorted(vaults, key=lambda v: (bool(v.get("open")), v.get("ts") or 0))[-1]
    path = Path(best["path"])
    return path if path.is_dir() else None


def find_vault(setting: str = "", config_file: Path | None = None) -> Path:
    if setting.strip():
        path = Path(os.path.expandvars(os.path.expanduser(setting.strip())))
        if not path.is_dir():
            raise VaultNotFound(f"The obsidian_vault folder does not exist: {path}")
        return path
    found = vault_from_obsidian(config_file or obsidian_config_path())
    if found is None:
        raise VaultNotFound("No Obsidian vault found. Set the obsidian_vault setting to your vault "
                            "folder (or open the vault in Obsidian once).")
    return found


# notes ----------------------------------------------------------------------------------------
def _yaml(value: Any) -> str:
    """A YAML scalar: JSON strings are valid double-quoted YAML."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _tag(t: str) -> str:
    """Obsidian tags take no spaces or punctuation except - _ /."""
    t = re.sub(r"[^\w/-]+", "-", t.strip().lower().lstrip("#"), flags=re.U).strip("-")
    return t if t and not t.isdigit() else ""


def owned_fields(c: dict[str, Any], exported: str) -> list[tuple[str, Any]]:
    tags = [t for t in dict.fromkeys(_tag(x) for x in c["tags"]) if t]
    return [("tweet_id", c["id"]), ("url", c["url"]), ("author", "@" + c["author"]),
            ("posted", c["date"]), ("category", c["category"]), ("tags", tags),
            ("kind", c["kind"]), ("priority", c["priority"]), ("summary", c["summary"]),
            ("why_saved", c["why"]), ("article", c["article"]), ("exported", exported)]


def front_matter_lines(fields: Iterable[tuple[str, Any]]) -> list[str]:
    out = []
    for key, value in fields:
        if isinstance(value, list):
            out.append(f"{key}:" + ("" if value else " []"))
            out += [f"  - {_yaml(v)}" for v in value]
        else:
            out.append(f"{key}: {_yaml(value)}")
    return out


def split_note(text: str) -> tuple[list[str] | None, str]:
    """(front matter lines or None, body)."""
    if not text.startswith("---"):
        return None, text
    lines = text.split("\n")
    for k in range(1, len(lines)):
        if lines[k].rstrip() == "---":
            return lines[1:k], "\n".join(lines[k + 1:])
    return None, text


def merge_front_matter(existing: list[str], fields: list[tuple[str, Any]]) -> list[str]:
    """Plugin keys replaced (first), every other key kept as written."""
    kept: list[str] = []
    skipping = False
    for line in existing:
        m = KEY_LINE.match(line)
        if m:
            skipping = m.group(1) in OWNED
        if not skipping:
            kept.append(line)
    return front_matter_lines(fields) + kept


def full_text(item: Item) -> str:
    text = html.unescape(item.article_text or item.text or "")
    text = TCO.sub("", text)
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def note_body(item: Item, c: dict[str, Any]) -> str:
    title = c["title"] or c["summary"] or (c["text"][:100] if c["text"] else "Bookmark")
    out = [f"# {title}", ""]
    if c["summary"] and c["title"]:
        out += [f"> [!summary] {c['summary']}", ""]
    if c["why"]:
        out += [f"*Why saved:* {c['why']}", ""]
    who = f"[@{c['author']}](https://x.com/{c['author']})"
    out += [f"{who} · {c['date']} · [open on X]({c['url']})", ""]
    body = full_text(item)
    if body:
        out += [body, ""]
    if c["quoted"]:
        quoted_by = f" (@{c['quotedAuthor']})" if c["quotedAuthor"] else ""
        out += [f"> Quoted{quoted_by}: " + c["quoted"].replace("\n", " "), ""]
    if c["image"]:
        out += [f"![]({c['image']})", ""]
    if c["links"]:
        out += ["Links:"] + [f"- {u}" for u in c["links"]] + [""]
    return "\n".join(out)


def note_name(c: dict[str, Any], taken: set[str]) -> str:
    head = c["title"] or c["summary"] or c["text"] or "bookmark"
    head = " ".join(BAD_NAME.sub(" ", head).split())[:70].rstrip(" .") or "bookmark"
    name = f"{head}.md"
    if name.lower() in taken:
        name = f"{head} ({c['id']}).md"
    taken.add(name.lower())
    return name


def index_notes(folder: Path) -> dict[str, Path]:
    """tweet_id -> note, for every note already in the folder (any depth)."""
    found: dict[str, Path] = {}
    for path in folder.rglob("*.md"):
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                head = "".join(next(fh, "") for _ in range(HEAD_LINES))
        except OSError:
            continue
        fm, _ = split_note(head)
        m = TWEET_ID.search("\n".join(fm)) if fm else None
        if m:
            found.setdefault(m.group(1), path)
    return found


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".xbm-tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def export(store: Store, *, vault: str = "", config_file: Path | None = None,
           now: _dt.datetime | None = None) -> ObsidianResult:
    root = find_vault(vault, config_file)
    folder = root / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    exported = (now or _dt.datetime.now()).strftime("%Y-%m-%d")
    res = ObsidianResult(folder=folder)
    existing = index_notes(folder)
    taken = {p.name.lower() for p in folder.iterdir()}
    for item, label in store.labelled_items():
        c = card(item, label)
        if c["category"] == UNSORTED:
            c["category"] = ""
        fields = owned_fields(c, exported)
        path = existing.get(item.id)
        try:
            if path is None:
                path = folder / note_name(c, taken)
                lines = front_matter_lines(fields) + ['status: "inbox"']
                _write(path, "---\n" + "\n".join(lines) + "\n---\n" + note_body(item, c))
                res.created += 1
                continue
            text = path.read_text(encoding="utf-8")
            fm, body = split_note(text)
            # "exported" changes every day; compare without it
            same = fm is not None and [ln for ln in merge_front_matter(fm, fields)
                                       if not ln.startswith("exported:")] == \
                [ln for ln in fm if not ln.startswith("exported:")]
            if same:
                res.unchanged += 1
                continue
            new_fm = merge_front_matter(fm or [], fields)
            _write(path, "---\n" + "\n".join(new_fm) + "\n---\n" + (body if fm else text))
            res.updated += 1
        except OSError as exc:
            res.errors.append(f"{path.name if path else item.id}: {exc.strerror or exc}")
    base = folder / BASE_FILE
    if not base.exists():
        _write(base, BASE_TEXT)
    return res
