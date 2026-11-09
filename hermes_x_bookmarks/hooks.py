"""``pre_llm_call``: make a bare "task 3" / "skill 2" / "done 1" reach the plugin.

A slash command's output (``/xbm digest``) is not part of the agent's conversation, so a reply
like "task 3" reaches an agent that has never seen the digest. When a message is only such a
reply and there is a recent digest, this adds a short note naming the item and the tool to call.
Every other message is left alone (one regex, no database access).
"""
from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Callable
from typing import Any

from . import commands
from .store import Store, open_db

REPLY = re.compile(r"^\s*/?(task|skill|done)\s*#?(\d{1,2})(?:\s+(.*))?\s*$", re.I | re.S)
MAX_AGE_DAYS = 8
MAX_LEN = 300   # a longer message is a real request, not a digest reply


def _text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):   # content blocks
        return " ".join(str(b.get("text", "")) for b in message if isinstance(b, dict))
    return ""


def _recent(created_at: str, now: _dt.datetime) -> bool:
    try:
        when = _dt.datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.UTC)
    except (TypeError, ValueError):
        return False
    return now - when <= _dt.timedelta(days=MAX_AGE_DAYS)


def note_for(store: Store, message: Any, now: _dt.datetime | None = None) -> str:
    text = _text(message)
    m = REPLY.match(text) if len(text) <= MAX_LEN else None
    if not m:
        return ""
    verb, n = m.group(1).lower(), int(m.group(2))
    if verb == "done":
        tasks = store.open_tasks()
        if not 1 <= n <= len(tasks):
            return ""
        return (f"[X bookmarks plugin] \"done {n}\" most likely means: finish open task #{n} from "
                "the user's X bookmarks tasks. Call the xbm_task tool with action \"done\" and "
                f"item \"{n}\", then show its text. If the user clearly means something else, "
                "ignore this note.")
    last = store.last_digest()
    now = now or _dt.datetime.now(_dt.UTC)
    if not last or not _recent(last["created_at"], now) or not 1 <= n <= len(last["item_ids"]):
        return ""
    from .actions import _line

    item = _line(store, last["item_ids"][n - 1])
    if verb == "task":
        how = (f"Call the xbm_task tool with action \"add\" and item \"{n}\""
               + (" and the rest of the message as note" if m.group(3) else "") + ".")
    else:
        how = (f"Call the xbm_skill tool with action \"draft\" and item \"{n}\", show the draft "
               "and ask before saving it (xbm_skill action \"save\").")
    return (f"[X bookmarks plugin] The user's message replies to their latest X bookmarks digest "
            f"(sent {last['created_at'][:10]}): item #{n} is {item}. {how} Then show the tool's "
            "text. If the user clearly means something else, ignore this note.")


def make_pre_llm_call(db_factory: commands.DbFactory | None = None
                      ) -> Callable[..., dict[str, str] | None]:
    def pre_llm_call(user_message: Any = None, **_kw: Any) -> dict[str, str] | None:
        text = _text(user_message)
        if len(text) > MAX_LEN or not REPLY.match(text):
            return None
        try:
            conn = (db_factory or open_db)()
        except Exception:  # noqa: BLE001 - a hook must never break a turn
            return None
        try:
            note = note_for(Store(conn), text)
        except Exception:  # noqa: BLE001
            note = ""
        finally:
            conn.close()
        return {"context": note} if note else None

    return pre_llm_call
