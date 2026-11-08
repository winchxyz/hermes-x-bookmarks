"""X API v2 client: who am I, bookmark pages, post lookups, rate limits and a cost meter.

HTTP goes through a :class:`~hermes_x_bookmarks.auth.Transport`, so this module never touches a
token. Read-only GETs only.
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from .auth import HttpResult, Transport

API = "https://api.x.com"

# Old ("tweet") parameter names: what the data dictionary, X staff and xurl use today.
TWEET_FIELDS = ("id,text,created_at,author_id,conversation_id,in_reply_to_user_id,"
                "referenced_tweets,entities,attachments,lang,public_metrics,note_tweet,article")
# No article.media_entities: Article inline images were half of all expanded resources on day 1
# (billable from 2026-11-22) and cannot be placed in the text anyway. The cover stays.
EXPANSIONS = "author_id,attachments.media_keys,referenced_tweets.id,article.cover_media"
USER_FIELDS = "id,name,username"
MEDIA_FIELDS = "media_key,type,url,preview_image_url,alt_text,width,height"

POST_PARAMS: dict[str, str] = {
    "tweet.fields": TWEET_FIELDS,
    "expansions": EXPANSIONS,
    "user.fields": USER_FIELDS,
    "media.fields": MEDIA_FIELDS,
}

# Paging stops early at max_results=100 for some accounts (X forum 257339); 90 worked there.
DEFAULT_PAGE_SIZE = 90
LOOKUP_BATCH = 100

# Pay-per-use prices (docs.x.com pricing, 2026-11). Owned reads: the reader owns the app.
OWNED_RATE = 0.001
STANDARD_RATES = {"post": 0.005, "user": 0.010, "media": 0.005}
EXPANSIONS_BILLED_FROM = _dt.date(2026, 11, 22)


class XApiError(RuntimeError):
    def __init__(self, status: int, title: str, detail: str = "", body: Any = None) -> None:
        super().__init__(f"X API {status}: {title}" + (f" ({detail})" if detail else ""))
        self.status = status
        self.title = title
        self.detail = detail
        self.body = body


class RateLimited(XApiError):
    def __init__(self, reset_at: int, body: Any = None) -> None:
        super().__init__(429, "Too Many Requests", f"window resets at unix {reset_at}", body)
        self.reset_at = reset_at


@dataclass
class RateInfo:
    limit: int | None = None
    remaining: int | None = None
    reset_at: int | None = None

    @classmethod
    def from_result(cls, res: HttpResult) -> RateInfo:
        def num(name: str) -> int | None:
            raw = res.header(name)
            return int(raw) if raw.isdigit() else None

        return cls(num("x-rate-limit-limit"), num("x-rate-limit-remaining"),
                   num("x-rate-limit-reset"))


@dataclass
class CostMeter:
    """Counts billable resources per run. An upper bound: X dedupes per UTC day."""

    today: _dt.date = field(default_factory=lambda: _dt.datetime.now(_dt.UTC).date())
    requests: int = 0
    posts: int = 0
    expanded_posts: int = 0
    users: int = 0
    media: int = 0
    usd: float = 0.0

    @property
    def expansions_billed(self) -> bool:
        return self.today >= EXPANSIONS_BILLED_FROM

    def add(self, payload: Mapping[str, Any], *, owned: bool) -> None:
        data = payload.get("data")
        posts = len(data) if isinstance(data, list) else (1 if isinstance(data, dict) else 0)
        inc = payload.get("includes") or {}
        n_tweets = len(inc.get("tweets") or [])
        n_users = len(inc.get("users") or [])
        n_media = len(inc.get("media") or [])
        self.requests += 1
        self.posts += posts
        self.expanded_posts += n_tweets
        self.users += n_users
        self.media += n_media
        if owned:
            cost = posts * OWNED_RATE
            if self.expansions_billed:
                cost += (n_tweets + n_users + n_media) * OWNED_RATE
        else:
            cost = posts * STANDARD_RATES["post"]
            if self.expansions_billed:
                cost += (n_tweets * STANDARD_RATES["post"] + n_users * STANDARD_RATES["user"]
                         + n_media * STANDARD_RATES["media"])
        self.usd += cost

    def as_dict(self) -> dict[str, Any]:
        return {"requests": self.requests, "posts": self.posts,
                "expanded_posts": self.expanded_posts, "users": self.users, "media": self.media,
                "expansions_billed": self.expansions_billed, "usd_estimate": round(self.usd, 4)}


def _error_from(res: HttpResult) -> XApiError:
    try:
        body = res.json()
    except ValueError:
        body = None
    title, detail = "error", ""
    if isinstance(body, dict):
        title = str(body.get("title") or body.get("error") or title)
        detail = str(body.get("detail") or body.get("error_description") or "")
        errs = body.get("errors")
        if not detail and isinstance(errs, list) and errs and isinstance(errs[0], dict):
            detail = str(errs[0].get("message") or errs[0].get("detail") or "")
    if res.status == 429:
        reset = res.header("x-rate-limit-reset")
        return RateLimited(int(reset) if reset.isdigit() else 0, body)
    return XApiError(res.status, title, detail, body)


class XApi:
    def __init__(self, transport: Transport, *, meter: CostMeter | None = None,
                 base: str = API) -> None:
        self.transport = transport
        self.meter = meter or CostMeter()
        self.base = base.rstrip("/")
        self.last_rate = RateInfo()

    def url(self, path: str, params: Mapping[str, Any] | None = None) -> str:
        query = urlencode({k: v for k, v in (params or {}).items() if v not in (None, "")},
                          safe=",.")
        return f"{self.base}{path}" + (f"?{query}" if query else "")

    def get(self, path: str, params: Mapping[str, Any] | None = None, *,
            owned: bool = False) -> dict[str, Any]:
        res = self.transport.get(self.url(path, params))
        self.last_rate = RateInfo.from_result(res)
        if not 200 <= res.status < 300:
            raise _error_from(res)
        payload = res.json()
        if not isinstance(payload, dict):
            raise XApiError(res.status, "unexpected response", type(payload).__name__)
        self.meter.add(payload, owned=owned)
        return payload

    def me(self) -> dict[str, Any]:
        payload = self.get("/2/users/me", {"user.fields": USER_FIELDS})
        data = payload.get("data")
        if not isinstance(data, dict) or not data.get("id"):
            raise XApiError(200, "users/me returned no user")
        return data

    def bookmark_pages(self, user_id: str, *, page_size: int = DEFAULT_PAGE_SIZE,
                       max_pages: int | None = None,
                       params: Mapping[str, str] | None = None) -> Iterator[dict[str, Any]]:
        """Yield raw bookmark pages, newest first, until X stops giving ``next_token``."""
        token: str | None = None
        pages = 0
        while True:
            query = {**(params or POST_PARAMS), "max_results": page_size,
                     "pagination_token": token}
            payload = self.get(f"/2/users/{user_id}/bookmarks", query, owned=True)
            pages += 1
            yield payload
            token = (payload.get("meta") or {}).get("next_token")
            if not token or (max_pages is not None and pages >= max_pages):
                return

    def tweets(self, ids: Iterable[str], params: Mapping[str, str] | None = None
               ) -> Iterator[dict[str, Any]]:
        """``GET /2/tweets`` in batches of 100 (standard price, also for your own posts)."""
        batch: list[str] = []
        for pid in dict.fromkeys(str(i) for i in ids):
            batch.append(pid)
            if len(batch) == LOOKUP_BATCH:
                yield self.get("/2/tweets", {**(params or POST_PARAMS), "ids": ",".join(batch)})
                batch = []
        if batch:
            yield self.get("/2/tweets", {**(params or POST_PARAMS), "ids": ",".join(batch)})
