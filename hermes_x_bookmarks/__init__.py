"""hermes-x-bookmarks: read your X bookmarks, sort them with your model, keep them where you work.

Official X API only (OAuth 2.0 user sign-in, read-only scopes). No scraping, no internal x.com
endpoints, no browser automation.
"""
from __future__ import annotations

from typing import Any

__version__ = "0.0.1"

PLUGIN_NAME = "hermes-x-bookmarks"


def register(ctx: Any) -> None:
    """Register the ``hermes xbm`` CLI command.

    Opens no sockets and imports nothing heavy: Plugin Doctor blocks the network while this runs.
    """
    from . import cli

    ctx.register_cli_command(
        name="xbm", help="X bookmarks: check the X sign-in and probe the API",
        setup_fn=cli.setup, handler_fn=cli.make_handler(ctx),
        description="hermes xbm whoami | probe")
