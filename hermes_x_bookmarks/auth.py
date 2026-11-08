"""Where the X bearer comes from. The plugin never stores a token (catalog rule 11).

Three backends, all behind one call shape ``transport.get(url) -> HttpResult``:

* ``keys``: OAuth 1.0a user context with the four values from your own developer app (Keys and
  tokens), stored in the Hermes profile's ``.env`` and read through Hermes' secret scope. No
  browser sign-in and no callback URL. ``auto`` (default) picks it when all four are set.
* ``hermes``: Hermes' plugin OAuth 2.0. The user signs in once with
  ``hermes auth add hermes-x-bookmarks:x``; Hermes keeps and refreshes the grant and attaches the
  bearer itself inside ``credentialed_provider_request``. This module never sees the token.
* ``xurl``: the official X CLI. ``xurl token`` prints a fresh access token (refreshing it first if
  needed); we keep it in memory for one run only and never read ``~/.xurl``.

No function here logs, prints or returns a token, including inside error messages.
"""
from __future__ import annotations

import json as _json
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

OAUTH_ID = "x"
SIGN_IN_HINT = "Run `hermes auth add hermes-x-bookmarks:x` in your own terminal to sign in to X."


class AuthUnavailable(RuntimeError):
    """No usable X sign-in. The message tells the user what to run; it never holds a token."""


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> Any:
        return _json.loads(self.body or b"null")

    def header(self, name: str) -> str:
        low = name.lower()
        return next((str(v) for k, v in self.headers.items() if k.lower() == low), "")


class Transport(Protocol):
    name: str

    def get(self, url: str) -> HttpResult: ...


class HermesTransport:
    """Every request goes through Hermes, which attaches the user's X grant for api.x.com only."""

    name = "hermes"

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def get(self, url: str) -> HttpResult:
        try:
            from hermes_cli.plugin_provider_requests import (
                ProviderNotSignedIn,
                credentialed_provider_request,
            )
        except ImportError as exc:  # outside Hermes
            raise AuthUnavailable("The Hermes sign-in needs a running Hermes. " + SIGN_IN_HINT
                                  ) from exc
        try:
            resp = credentialed_provider_request(OAUTH_ID, "GET", url, timeout=self.timeout)
        except ProviderNotSignedIn as exc:
            raise AuthUnavailable(str(exc) or SIGN_IN_HINT) from None
        except Exception as exc:  # noqa: BLE001  AuthError on refresh, client id missing, ...
            code = getattr(exc, "code", "") or type(exc).__name__
            raise AuthUnavailable(f"X sign-in failed ({code}): {exc}. {SIGN_IN_HINT}") from None
        return HttpResult(resp.status, dict(resp.headers), resp.body)


def _run_xurl_token(app: str, timeout: float = 30.0) -> str:
    exe = shutil.which("xurl")
    if not exe:
        raise AuthUnavailable("The xurl sign-in needs the `xurl` CLI on PATH "
                              "(https://github.com/xdevplatform/xurl).")
    cmd = [exe, "token"] + (["--app", app] if app else [])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuthUnavailable(f"`xurl token` did not run ({type(exc).__name__}).") from None
    token = (out.stdout or "").strip().splitlines()[-1].strip() if out.stdout.strip() else ""
    if out.returncode != 0 or not token or " " in token:
        # stderr may name the app or user; never the token (xurl prints that on stdout)
        raise AuthUnavailable("`xurl token` gave no token. Sign in with `xurl auth oauth2"
                              + (f" --app {app}" if app else "") + "` in your own terminal.")
    return token


@dataclass
class XurlTransport:
    """Bearer from ``xurl token``, cached in memory for a few minutes, refetched once on 401."""

    app: str = ""
    timeout: float = 30.0
    token_source: Callable[[str], str] = _run_xurl_token
    max_age_s: float = 600.0
    clock: Callable[[], float] = time.monotonic
    name: str = field(default="xurl", init=False)
    _token: str = field(default="", init=False, repr=False)
    _at: float = field(default=0.0, init=False, repr=False)

    def _bearer(self, fresh: bool = False) -> str:
        if fresh or not self._token or self.clock() - self._at > self.max_age_s:
            self._token = self.token_source(self.app)
            self._at = self.clock()
        return self._token

    def _send(self, url: str, token: str) -> HttpResult:
        import httpx

        try:
            r = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=self.timeout,
                          follow_redirects=False)
        except httpx.HTTPError as exc:
            raise ConnectionError(f"X request failed ({type(exc).__name__})") from None
        return HttpResult(r.status_code, dict(r.headers), r.content)

    def get(self, url: str) -> HttpResult:
        res = self._send(url, self._bearer())
        if res.status == 401:
            res = self._send(url, self._bearer(fresh=True))
        return res


@dataclass
class KeysTransport:
    """OAuth 1.0a user context: each GET is signed with the owner's app keys (HMAC-SHA1)."""

    timeout: float = 30.0
    environ: Mapping[str, str] | None = None
    name: str = field(default="keys", init=False)

    def get(self, url: str) -> HttpResult:
        import httpx

        from . import oauth1, secrets

        missing = secrets.missing_x_keys(self.environ)
        if missing:
            raise AuthUnavailable("Missing in the Hermes profile's .env: " + ", ".join(missing)
                                  + ". Copy them from your X app's Keys and tokens page.")
        keys = secrets.x_keys(self.environ)
        header = oauth1.authorization_header(
            "GET", url, consumer_key=keys["XBM_X_API_KEY"],
            consumer_secret=keys["XBM_X_API_SECRET"], token=keys["XBM_X_ACCESS_TOKEN"],
            token_secret=keys["XBM_X_ACCESS_TOKEN_SECRET"])
        keys = {}
        try:
            r = httpx.get(url, headers={"Authorization": header}, timeout=self.timeout,
                          follow_redirects=False)
        except httpx.HTTPError as exc:
            raise ConnectionError(f"X request failed ({type(exc).__name__})") from None
        return HttpResult(r.status_code, dict(r.headers), r.content)


def make_transport(config: Mapping[str, Any] | None = None,
                   environ: Mapping[str, str] | None = None) -> Transport:
    from . import secrets

    cfg = dict(config or {})
    backend = str(cfg.get("auth_backend") or "auto").strip().lower()
    if backend == "auto":
        backend = "keys" if not secrets.missing_x_keys(environ) else "hermes"
    if backend == "keys":
        return KeysTransport(environ=environ)
    if backend == "xurl":
        return XurlTransport(app=str(cfg.get("xurl_app") or "").strip())
    return HermesTransport()
