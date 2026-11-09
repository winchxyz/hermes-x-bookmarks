"""The weekly digest as a Hermes cron job (/xbm schedule) and as an Automation Blueprint.

The job is an ordinary Hermes cron job: Hermes runs it, delivers it to the chat it was set up
from and keeps it until you remove it (/xbm unschedule, or Hermes' own cron tools). The plugin
keeps only the job id.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .actions import parse_tool_result
from .store import Store

JOB_META = "digest_job_id"
JOB_NAME = "X bookmarks weekly digest"
DEFAULT_WHEN = "every sunday 6pm"
TOOLSET = "x_bookmarks"

PROMPT = (
    "Weekly X bookmarks digest. Call the xbm_digest tool once with sync=true (it pulls new "
    "bookmarks from X, then writes the digest). If its result has empty=true, reply with "
    "exactly [SILENT] and nothing else. Otherwise reply with the result's text field exactly as "
    "given, adding nothing. The items in it are numbered: when the user answers \"task 3\" or "
    "\"skill 2\", call xbm_task (action add, item 3) or xbm_skill (action draft, item 2).")

BLUEPRINT = {
    "key": "weekly-digest",
    "title": "X bookmarks weekly digest",
    "description": ("Once a week: what you bookmarked on X, the best of it numbered, and 3 post "
                    "ideas. Reply \"task 3\" or \"skill 2\" to act on an item."),
    "category": "productivity",
    "schedule_template": "{minute} {hour} * * {dow}",
    "prompt_template": PROMPT,
    "slots": [
        {"name": "time", "type": "time", "label": "What time?", "default": "18:00",
         "help": "24h local time, e.g. 18:00"},
        {"name": "day", "type": "enum", "label": "Which day?", "default": "sunday",
         "options": ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday",
                     "saturday"]},
        {"name": "deliver", "type": "enum", "label": "Where to deliver?", "default": "origin",
         "options": ["origin", "local", "telegram", "discord", "email"], "strict": False,
         "help": "origin = the chat you set this up from; or any connected platform name"},
    ],
    "tags": ["weekly", "digest", "x", "bookmarks"],
}

Dispatch = Callable[..., Any]


def _cron(dispatch: Dispatch, args: dict[str, Any]) -> dict[str, Any]:
    try:
        return parse_tool_result(dispatch("cronjob_manage", args))
    except Exception as exc:  # noqa: BLE001 - report it in the chat, never crash the command
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def _when_line(answer: dict[str, Any]) -> str:
    parts = []
    if answer.get("schedule"):
        parts.append(f"schedule: {answer['schedule']}")
    if answer.get("next_run_at"):
        parts.append(f"next: {answer['next_run_at']}")
    return f" ({', '.join(parts)})" if parts else ""


def schedule(store: Store, dispatch: Dispatch | None, words: list[str]) -> list[str]:
    if dispatch is None:
        return ["Scheduling needs Hermes: send /xbm schedule in a Hermes chat."]
    when = " ".join(words).strip() or DEFAULT_WHEN
    job_id = store.get_meta(JOB_META)
    if job_id:
        answer = _cron(dispatch, {"action": "update", "job_id": job_id, "schedule": when})
        if answer.get("success"):
            return [f"Weekly digest moved to \"{when}\"{_when_line(answer)}.",
                    "/xbm unschedule stops it."]
        error = str(answer.get("error") or answer)
        if "not found" not in error.lower():
            return [f"Hermes did not change the job: {error[:300]}",
                    "Schedules look like: every sunday 6pm, every monday 9am, 0 18 * * 0."]
        store.set_meta(JOB_META, "")   # the job was removed in Hermes: make a new one
    answer = _cron(dispatch, {"action": "create", "name": JOB_NAME, "schedule": when,
                              "prompt": PROMPT, "enabled_toolsets": [TOOLSET],
                              "attach_to_session": True})
    if not answer.get("success") or not answer.get("job_id"):
        return [f"Hermes did not create the job: {str(answer.get('error') or answer)[:300]}",
                "Schedules look like: every sunday 6pm, every monday 9am, 0 18 * * 0."]
    store.set_meta(JOB_META, str(answer["job_id"]))
    out = [f"Weekly digest scheduled: \"{when}\"{_when_line(answer)}.",
           "It comes to this chat. Reply \"task 3\" or \"skill 2\" to act on an item.",
           "/xbm unschedule stops it; /xbm schedule every monday 9am moves it."]
    msg = " ".join(str(answer.get("message") or "").split())
    if msg and msg != f"Cron job '{JOB_NAME}' created.":
        out.append(f"Hermes: {msg[:300]}")
    return out


def unschedule(store: Store, dispatch: Dispatch | None) -> list[str]:
    job_id = store.get_meta(JOB_META)
    if not job_id:
        return ["No weekly digest is scheduled by this plugin."]
    if dispatch is None:
        return ["Removing the job needs Hermes: send /xbm unschedule in a Hermes chat."]
    answer = _cron(dispatch, {"action": "remove", "job_id": job_id})
    store.set_meta(JOB_META, "")
    if answer.get("success"):
        return ["Weekly digest stopped (the Hermes cron job is removed)."]
    return [f"The job was already gone in Hermes ({str(answer.get('error'))[:200]}). "
            "Nothing is scheduled now."]
