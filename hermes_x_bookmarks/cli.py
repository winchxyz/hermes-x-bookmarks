"""``hermes xbm whoami`` and ``hermes xbm probe``.

Run in your own terminal. Output names ids and counts, never a token.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from . import auth
from .xapi import XApi, XApiError


def setup(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="xbm_cmd")
    for name, help_text in (("whoami", "Check the X sign-in: print your X user id and handle"),
                            ("probe", "Day-1 spike: ask X how bookmarks and Articles come back")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--backend", choices=["auto", "keys", "hermes", "xurl"], default=None,
                       help="X sign-in to use (default: the plugin setting, else auto)")
        p.add_argument("--xurl-app", default=None, help="xurl app name (xurl backend only)")
        if name == "probe":
            p.add_argument("--max-pages", type=int, default=10,
                           help="Stop the full bookmark run after this many pages (90 posts each)")


def _config(ctx: Any, args: argparse.Namespace) -> dict[str, Any]:
    getter = getattr(ctx, "get_config", None) if ctx is not None else None
    cfg = {k: getter(k) for k in ("auth_backend", "xurl_app")} if getter else {}
    if getattr(args, "backend", None):
        cfg["auth_backend"] = args.backend
    if getattr(args, "xurl_app", None):
        cfg["xurl_app"] = args.xurl_app
    return cfg


def make_handler(ctx: Any = None, *, api_factory: Callable[[dict], XApi] | None = None
                 ) -> Callable[[argparse.Namespace], int]:
    def build(cfg: dict) -> XApi:
        return api_factory(cfg) if api_factory else XApi(auth.make_transport(cfg))

    def handler(args: argparse.Namespace) -> int:
        cmd = getattr(args, "xbm_cmd", None)
        if cmd not in ("whoami", "probe"):
            print("usage: hermes xbm {whoami|probe}")
            return 2
        api = build(_config(ctx, args))
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
                print(line)
            print(f"\nraw responses and report.json: {out}")
            return 0
        except auth.AuthUnavailable as exc:
            print(f"X sign-in unavailable: {exc}")
            return 1
        except XApiError as exc:
            print(str(exc))
            return 1

    return handler
