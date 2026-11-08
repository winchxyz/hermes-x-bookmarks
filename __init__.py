"""Hermes entry point. Hermes imports this file by path and calls ``register(ctx)``.

All logic lives in the ``hermes_x_bookmarks`` package next to this file; the relative import works
because Hermes loads the plugin directory as a package. The absolute fallback only matters when
a tool (pytest collecting the repo root, say) imports this file as a bare module.
"""
try:
    from .hermes_x_bookmarks import register
except ImportError:  # pragma: no cover - bare-module import outside Hermes
    from hermes_x_bookmarks import register

__all__ = ["register"]
