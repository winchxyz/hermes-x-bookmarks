"""Tools for the Hermes agent (toolset ``x_bookmarks``): the weekly cron job writes its digest
with ``xbm_digest``, and a reply such as "task 3" or "skill 2" reaches ``xbm_task`` /
``xbm_skill``. Every handler returns a JSON string and never raises.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from . import actions, auth, commands, digest
from .store import Store, open_db

TOOLSET = "x_bookmarks"

ITEM = {"type": "string",
        "description": "The bookmark: its number in the latest digest (\"3\"), its post id or its "
                       "x.com link."}

DIGEST_SCHEMA = {
    "name": "xbm_digest",
    "description": ("Write a digest of the user's recent X bookmarks: counts per category, a short "
                    "overview, the best ones numbered, and 3 post ideas. The numbers are what "
                    "xbm_task and xbm_skill take. Returns {text, empty, new}; show text as it is."),
    "parameters": {"type": "object", "properties": {
        "days": {"type": "integer", "description": "How many days back (default 7)."},
        "sync": {"type": "boolean",
                 "description": "Pull new bookmarks from X first (default false)."}}},
}

TASK_SCHEMA = {
    "name": "xbm_task",
    "description": ("The user's tasks made from X bookmarks. add: make a bookmark a task (the user "
                    "says \"task 3\" after a digest), done: finish one, list: open tasks."),
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["add", "done", "list"]},
        "item": ITEM,
        "note": {"type": "string", "description": "Optional note for add."}},
        "required": ["action"]},
}

SKILL_SCHEMA = {
    "name": "xbm_skill",
    "description": ("Turn an X bookmark into a Hermes skill. draft: write a draft from the post "
                    "and return it (the user says \"skill 2\" after a digest); show it and ask "
                    "before saving. save: create the drafted skill, only after the user agreed."),
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["draft", "save"]},
        "item": ITEM},
        "required": ["action", "item"]},
}


def _ok(text: str, **extra: Any) -> str:
    return json.dumps({"success": True, "text": text, **extra}, ensure_ascii=False)


def _err(text: str) -> str:
    return json.dumps({"success": False, "error": text}, ensure_ascii=False)


def make_handlers(ctx: Any, *, db_factory: commands.DbFactory | None = None,
                  api_factory: commands.ApiFactory | None = None
                  ) -> dict[str, Callable[..., str]]:
    def with_store(fn: Callable[[Store], str]) -> str:
        try:
            conn = (db_factory or open_db)()
        except Exception as exc:  # noqa: BLE001
            return _err(f"Cannot open the bookmarks database: {type(exc).__name__}")
        try:
            return fn(Store(conn))
        except actions.ActionError as exc:
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001 - a tool must answer, not raise
            return _err(f"{type(exc).__name__}: {exc}"[:300])
        finally:
            conn.close()

    def xbm_digest(args: dict[str, Any] | None = None, **_kw: Any) -> str:
        args = args or {}
        days = int(args.get("days") or digest.DAYS)

        def go(store: Store) -> str:
            cfg = commands.config_of(ctx)
            notes: list[str] = []
            if args.get("sync"):
                try:
                    api = (api_factory or commands.default_api)(cfg)
                    notes = commands.do_sync(api, store)
                except auth.AuthUnavailable as exc:
                    notes = [f"X sign-in unavailable, digest from stored bookmarks: {exc}"]
                except Exception as exc:  # noqa: BLE001 - still write the digest
                    notes = [f"Sync failed, digest from stored bookmarks: {type(exc).__name__}"]
            res = digest.build(store, commands.llm_of(ctx), days=max(1, min(days, 90)),
                               language=str(cfg.get("classify_language") or "English"),
                               about_me=str(cfg.get("about_me") or ""))
            return _ok(res.text, empty=res.empty, new=res.new, sync=notes)

        return with_store(go)

    def xbm_task(args: dict[str, Any] | None = None, **_kw: Any) -> str:
        args = args or {}
        action = str(args.get("action") or "list").lower()
        item = str(args.get("item") or "")

        def go(store: Store) -> str:
            if action == "add":
                return _ok(actions.add_task(store, item, str(args.get("note") or "")))
            if action == "done":
                return _ok(actions.finish_task(store, item))
            return _ok(actions.list_tasks(store))

        return with_store(go)

    def xbm_skill(args: dict[str, Any] | None = None, **_kw: Any) -> str:
        args = args or {}
        action = str(args.get("action") or "draft").lower()
        item = str(args.get("item") or "")

        def go(store: Store) -> str:
            if action == "save":
                return _ok(actions.save_skill(store, commands.dispatch_of(ctx), item))
            cfg = commands.config_of(ctx)
            return _ok(actions.draft_skill(
                store, commands.llm_of(ctx), item,
                language=str(cfg.get("classify_language") or "English")))

        return with_store(go)

    return {"xbm_digest": xbm_digest, "xbm_task": xbm_task, "xbm_skill": xbm_skill}


SCHEMAS = {"xbm_digest": DIGEST_SCHEMA, "xbm_task": TASK_SCHEMA, "xbm_skill": SKILL_SCHEMA}
EMOJI = {"xbm_digest": "🗞️", "xbm_task": "✅", "xbm_skill": "🧩"}


def register(ctx: Any) -> None:
    reg = getattr(ctx, "register_tool", None)
    if reg is None:
        return
    for name, handler in make_handlers(ctx).items():
        schema = SCHEMAS[name]
        reg(name=name, toolset=TOOLSET, schema=schema, handler=handler,
            description=schema["description"], emoji=EMOJI[name])
