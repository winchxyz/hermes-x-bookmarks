"""hermes-x-bookmarks: read your X bookmarks, sort them with your model, keep them where you work.

Official X API only (OAuth 2.0 user sign-in, read-only scopes). No scraping, no internal x.com
endpoints, no browser automation.
"""
from __future__ import annotations

from typing import Any

__version__ = "0.0.1"

PLUGIN_NAME = "hermes-x-bookmarks"


def register(ctx: Any) -> None:
    """Register ``/xbm`` in chats and ``hermes xbm`` in the terminal.

    Opens no sockets, no database and imports nothing heavy: Plugin Doctor blocks the network
    while this runs.
    """
    from . import classify, cli, commands

    register_aux = getattr(ctx, "register_auxiliary_task", None)
    if register_aux is not None:
        # Own model slot; provider "auto" means the user's main model until they pin another one.
        register_aux(classify.AUX_TASK, display_name="X bookmarks: sorting",
                     description="Sorts saved X bookmarks into categories (batches of 10)")
    ctx.register_command(
        "xbm", commands.make_slash_handler(ctx),
        description="X bookmarks: sync, classify, status, list",
        args_hint="sync [full] | classify [N] | status | list [N] [category]")
    ctx.register_cli_command(
        name="xbm", help="X bookmarks: sign-in check, sync, classify, status, list",
        setup_fn=cli.setup, handler_fn=cli.make_handler(ctx),
        description="hermes xbm whoami | probe | sync | classify | status | list")
