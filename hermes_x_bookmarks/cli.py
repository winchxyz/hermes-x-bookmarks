"""``hermes xbm whoami | probe | sync | status | list``.

Run in your own terminal. Output names ids and counts, never a token.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

from . import auth, commands
from .xapi import XApi, XApiError

COMMANDS = (
    ("whoami", "Check the X sign-in: print your X user id and handle"),
    ("probe", "Day-1 spike: ask X how bookmarks and Articles come back"),
    ("sync", "Pull new bookmarks from X into the local store"),
    ("classify", "Sort unsorted bookmarks with your Hermes model"),
    ("export", "Write bookmarks out: desktop (board + Markdown), obsidian, notion, gdocs"),
    ("status", "How many bookmarks are stored, categories, last runs and their cost"),
    ("list", "Show the most recent stored bookmarks"),
    ("about", "Show or set what you build and follow (used to judge priority)"),
    ("digest", "The last 7 days of bookmarks: overview, the best ones numbered, post ideas"),
    ("task", "Make item N of the latest digest a task: task N [note]"),
    ("tasks", "List open tasks"),
    ("done", "Finish a task: done N (its number in 'tasks')"),
    ("skill", "Draft a Hermes skill from item N: skill N; skill N save creates it"),
    ("schedule", "Send the digest weekly as a Hermes cron job (default: every sunday 6pm)"),
    ("unschedule", "Stop the weekly digest"),
)
COMMANDS_RUN = ("sync", "classify", "export", "status", "list", "about", "digest", "task",
                "tasks", "done", "skill", "schedule", "unschedule")
WORDS = ("digest", "task", "done", "skill", "schedule")
NEEDS_X = ("whoami", "probe", "sync")


def setup(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="xbm_cmd")
    for name, help_text in COMMANDS:
        p = sub.add_parser(name, help=help_text)
        if name in NEEDS_X:
            p.add_argument("--backend", choices=["auto", "keys", "hermes", "xurl"], default=None,
                           help="X sign-in to use (default: the plugin setting, else auto)")
            p.add_argument("--xurl-app", default=None, help="xurl app name (xurl backend only)")
        if name == "probe":
            p.add_argument("--max-pages", type=int, default=10,
                           help="Stop the full bookmark run after this many pages (90 posts each)")
        if name == "sync":
            p.add_argument("--full", action="store_true",
                           help="Re-read all bookmarks instead of stopping at stored ones")
            p.add_argument("--max-pages", type=int, default=None,
                           help="Stop after this many pages (default: no limit)")
        if name == "list":
            p.add_argument("--limit", type=int, default=10, help="How many (max 100)")
            p.add_argument("--category", default="", help="Only this category (or its start)")
        if name == "classify":
            p.add_argument("--limit", type=int, default=20,
                           help="Sort at most this many, most recent first (default 20)")
            p.add_argument("--all", action="store_true", help="Sort every unsorted bookmark")
        if name == "export":
            p.add_argument("where", nargs="*",
                           help="desktop, obsidian, notion [page URL], gdocs or all "
                                "(default: the export_to setting, else desktop)")
            p.add_argument("--dir", default=None,
                           help="Folder to write to (default: the export_dir setting, else "
                                "'X Bookmarks' on your Desktop)")
        if name == "about":
            p.add_argument("text", nargs="*", help="New text, or 'clear'; empty shows it")
        if name in WORDS:
            p.add_argument("words", nargs="*", help={
                "digest": "Days back (default 7)", "task": "Item number, then an optional note",
                "done": "Task number", "skill": "Item number, then 'save' to create it",
                "schedule": "When, e.g. every monday 9am (default: every sunday 6pm)"}[name])


def say(line: str) -> None:
    """print() that survives a console without UTF-8 (Windows cp1252): emoji become '?'."""
    try:
        print(line)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, errors="replace").decode(enc, errors="replace"))


def _overrides(args: argparse.Namespace) -> dict[str, Any]:
    return {"auth_backend": getattr(args, "backend", None),
            "xurl_app": getattr(args, "xurl_app", None),
            "export_dir": getattr(args, "dir", None)}


def make_handler(ctx: Any = None, *, api_factory: Callable[[dict], XApi] | None = None,
                 db_factory: commands.DbFactory | None = None
                 ) -> Callable[[argparse.Namespace], int]:
    def build(cfg: dict) -> XApi:
        return api_factory(cfg) if api_factory else commands.default_api(cfg)

    def handler(args: argparse.Namespace) -> int:
        cmd = getattr(args, "xbm_cmd", None)
        if cmd not in {c for c, _ in COMMANDS}:
            print("usage: hermes xbm {" + "|".join(c for c, _ in COMMANDS) + "}")
            return 2
        if cmd in COMMANDS_RUN:
            words = [cmd]
            if cmd == "sync" and args.full:
                words.append("full")
            if cmd == "list":
                words.append(str(args.limit))
                words.extend(str(getattr(args, "category", "") or "").split())
            if cmd == "classify":
                words.append("all" if args.all else str(max(1, args.limit)))
            if cmd == "about":
                words.extend(getattr(args, "text", None) or [])
            if cmd == "export":
                words.extend(getattr(args, "where", None) or [])
            if cmd in WORDS:
                words.extend(getattr(args, "words", None) or [])
            lines = commands.run(words, ctx=ctx, api_factory=build, db_factory=db_factory,
                                 overrides=_overrides(args), log=say,
                                 max_pages=getattr(args, "max_pages", None), classify_cap=None)
            for line in lines:
                say(line)
            failed = lines and lines[0].startswith(
                ("Sync failed", "X sign-in unavailable", "No model access", "Export failed"))
            return 1 if failed else 0
        api = build(commands.config_of(ctx, _overrides(args)))
        try:
            if cmd == "whoami":
                me = api.me()
                print(f"X sign-in ok ({api.transport.name}): "
                      f"@{me.get('username')} id {me.get('id')}")
                return 0
            from . import probe

            out = probe.default_out_dir()
            report = probe.run_probe(api, out, max_pages=max(1, int(args.max_pages)))
            print("")
            for line in probe.summary_lines(report):
                say(line)
            print(f"\nraw responses and report.json: {out}")
            return 0
        except auth.AuthUnavailable as exc:
            print(f"X sign-in unavailable: {exc}")
            return 1
        except XApiError as exc:
            print(str(exc))
            return 1

    return handler
