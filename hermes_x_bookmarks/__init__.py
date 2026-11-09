"""hermes-x-bookmarks: read your X bookmarks, sort them with your model, keep them where you work.

Official X API only (read-only access with your own X app). No scraping, no internal x.com
endpoints, no browser automation.
"""
from __future__ import annotations

from typing import Any

__version__ = "0.3.0"

PLUGIN_NAME = "hermes-x-bookmarks"


def register(ctx: Any) -> None:
    """Register ``/xbm`` in chats and ``hermes xbm`` in the terminal.

    Opens no sockets, no database and imports nothing heavy: Plugin Doctor blocks the network
    while this runs.
    """
    from . import automation, classify, cli, commands, digest, tools

    register_aux = getattr(ctx, "register_auxiliary_task", None)
    if register_aux is not None:
        # Own model slots; provider "auto" means the user's main model until they pin another one.
        register_aux(classify.AUX_TASK, display_name="X bookmarks: sorting",
                     description="Sorts saved X bookmarks into categories (batches of 10)")
        register_aux(digest.AUX_TASK, display_name="X bookmarks: digest and skills",
                     description="Writes the weekly digest overview and post ideas, and drafts "
                                 "skills from bookmarks")
    ctx.register_command(
        "xbm", commands.make_slash_handler(ctx),
        description="X bookmarks: sync, classify, export, digest, tasks, skills, schedule",
        args_hint=("sync | classify [N] | export [desktop|obsidian|notion|gdocs] | digest"
                   " | task N | tasks | skill N [save] | schedule [when] | status | list"))
    ctx.register_cli_command(
        name="xbm", help="X bookmarks: sync, classify, export, digest, tasks, skills, schedule",
        setup_fn=cli.setup, handler_fn=cli.make_handler(ctx),
        description=("hermes xbm whoami | probe | sync | classify | export | digest | task | tasks"
                     " | done | skill | schedule | unschedule | status | list | about"))
    tools.register(ctx)
    from . import hooks

    # A slash command's output never reaches the agent: this lets a bare "task 3" find the digest.
    ctx.register_hook("pre_llm_call", hooks.make_pre_llm_call())
    blueprint = getattr(ctx, "register_automation_blueprint", None)
    if blueprint is not None:
        spec = dict(automation.BLUEPRINT)
        blueprint(spec.pop("key"), **spec)
