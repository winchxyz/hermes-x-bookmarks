"""Profile-scoped secret lookup.

Inside Hermes the values come from ``agent.secret_scope.get_secret`` (the profile's ``.env``).
Outside Hermes (unit tests, a bare script) that module is absent; then, and only then, the
process environment is used. A scope error fails closed: the secret is reported missing.

No function here logs, prints or returns a secret inside an error message.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

X_KEY_NAMES = ("XBM_X_API_KEY", "XBM_X_API_SECRET", "XBM_X_ACCESS_TOKEN",
               "XBM_X_ACCESS_TOKEN_SECRET")


def get(name: str, environ: Mapping[str, str] | None = None) -> str:
    """Value of secret ``name`` or ``""`` when unset. ``environ`` (tests) wins when given."""
    if environ is not None:
        return str(environ.get(name) or "").strip()
    try:
        from agent.secret_scope import get_secret
    except ImportError:
        return (os.environ.get(name) or "").strip()
    try:
        return str(get_secret(name) or "").strip()
    except Exception:  # noqa: BLE001  unscoped secret etc.: fail closed, no os.environ
        return ""


def x_keys(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The four OAuth 1.0a values; missing ones are empty strings."""
    return {name: get(name, environ) for name in X_KEY_NAMES}


def missing_x_keys(environ: Mapping[str, str] | None = None) -> list[str]:
    return [name for name, value in x_keys(environ).items() if not value]
