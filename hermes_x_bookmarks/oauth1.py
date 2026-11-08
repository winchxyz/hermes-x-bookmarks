"""OAuth 1.0a user-context signing (RFC 5849, HMAC-SHA1) for read-only X GETs.

X accepts OAuth 1.0a user context on ``GET /2/users/:id/bookmarks``. The four values come from
the owner's own developer app (Keys and tokens: API Key and Secret, Access Token and Secret) and
live in the Hermes profile's ``.env``; this module only signs one request at a time and never
logs, prints or returns them.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets as _secrets
import time
from collections.abc import Callable, Mapping
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit


def pct(value: str) -> str:
    """RFC 3986 percent-encoding, as OAuth 1.0a requires."""
    return quote(str(value), safe="~-._")


def base_string(method: str, url: str, params: list[tuple[str, str]]) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    port = parts.port
    default = (parts.scheme == "https" and port in (None, 443)) or (
        parts.scheme == "http" and port in (None, 80))
    netloc = host if default else f"{host}:{port}"
    base_url = urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", "", ""))
    encoded = sorted((pct(k), pct(v)) for k, v in params)
    norm = "&".join(f"{k}={v}" for k, v in encoded)
    return "&".join((method.upper(), pct(base_url), pct(norm)))


def signature(method: str, url: str, oauth_params: Mapping[str, str], consumer_secret: str,
              token_secret: str) -> str:
    query = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    base = base_string(method, url, [*query, *oauth_params.items()])
    key = f"{pct(consumer_secret)}&{pct(token_secret)}".encode()
    digest = hmac.new(key, base.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def authorization_header(method: str, url: str, *, consumer_key: str, consumer_secret: str,
                         token: str, token_secret: str,
                         nonce: Callable[[], str] = lambda: _secrets.token_hex(16),
                         clock: Callable[[], float] = time.time) -> str:
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce(),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(clock())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    oauth["oauth_signature"] = signature(method, url, oauth, consumer_secret, token_secret)
    return "OAuth " + ", ".join(f'{pct(k)}="{pct(v)}"' for k, v in sorted(oauth.items()))
