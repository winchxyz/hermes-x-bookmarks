"""Pull bookmarks from X into the store.

* First sync (empty store) or ``full=True``: big pages (90) until X stops giving ``next_token``.
* Later syncs: small pages (20), newest first, and stop once ``STOP_AFTER_KNOWN`` bookmarks in a
  row are already stored. A run of known ids (not just one) covers a re-bookmarked old post
  jumping to the top while newer bookmarks sit below it.

Every page is stored as it arrives, so a rate limit or an error keeps what came before it.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import reader
from .store import Store
from .xapi import DEFAULT_PAGE_SIZE, RateLimited, XApi, XApiError

INCREMENTAL_PAGE_SIZE = 20
STOP_AFTER_KNOWN = 5


@dataclass
class SyncResult:
    kind: str
    status: str = "ok"            # ok | rate_limited | error
    stop_reason: str = ""         # end | known | max_pages | rate_limited | error
    pages: int = 0
    fetched: int = 0
    new: int = 0
    articles_filled: int = 0
    total: int = 0
    error: str = ""
    reset_at: int | None = None
    cost: dict[str, Any] = field(default_factory=dict)

    def lines(self) -> list[str]:
        head = {"ok": "Sync done", "rate_limited": "Sync paused by the X rate limit",
                "error": "Sync failed"}[self.status]
        out = [f"{head} ({self.kind}): {self.new} new, {self.fetched} read in {self.pages} "
               f"page(s); {self.total} bookmarks stored."]
        why = {"end": "reached the end of your bookmarks",
               "known": "caught up with bookmarks already stored",
               "max_pages": "stopped at the page limit"}.get(self.stop_reason)
        if why:
            out.append(f"Stopped: {why}.")
        if self.articles_filled:
            out.append(f"Article bodies fetched separately: {self.articles_filled}.")
        if self.reset_at:
            out.append(f"X rate limit resets at unix time {self.reset_at}; run sync again then.")
        if self.error:
            out.append(f"Error: {self.error}")
        if self.cost:
            out.append(f"X API: {self.cost.get('requests', 0)} request(s), about "
                       f"${self.cost.get('usd_estimate', 0):.3f}.")
        return out


def user_id(api: XApi, store: Store) -> str:
    uid = store.get_meta("x_user_id")
    if not uid:
        me = api.me()
        uid = str(me["id"])
        store.set_meta("x_user_id", uid)
        store.set_meta("x_username", str(me.get("username") or ""))
    return uid


def sync(api: XApi, store: Store, *, full: bool = False, max_pages: int | None = None,
         log: Callable[[str], None] | None = None) -> SyncResult:
    say = log or (lambda _msg: None)
    first = store.count(include_removed=True) == 0
    kind = "full" if (full or first) else "incremental"
    page_size = DEFAULT_PAGE_SIZE if kind == "full" else INCREMENTAL_PAGE_SIZE
    result = SyncResult(kind=kind)
    run = store.start_run(kind)
    known_streak = 0
    try:
        uid = user_id(api, store)
        more = False
        for payload in api.bookmark_pages(uid, page_size=page_size, max_pages=max_pages):
            result.pages += 1
            items = reader.read_page(payload)
            result.articles_filled += _fill_missing_articles(api, items)
            known = store.known_ids(i.id for i in items)
            caught_up = False
            keep: list[reader.Item] = []
            for item in items:
                keep.append(item)
                known_streak = known_streak + 1 if item.id in known else 0
                if kind == "incremental" and known_streak >= STOP_AFTER_KNOWN:
                    caught_up = True
                    break
            new_ids = store.save_page(run, keep)
            result.fetched += len(items)
            result.new += len(new_ids)
            store.update_run(run, pages=result.pages, fetched=result.fetched, new=result.new)
            say(f"page {result.pages}: {len(items)} read, {len(new_ids)} new")
            if caught_up:
                break
            more = bool((payload.get("meta") or {}).get("next_token"))
        result.stop_reason = ("known" if known_streak >= STOP_AFTER_KNOWN and kind == "incremental"
                              else "max_pages" if more else "end")
    except RateLimited as exc:
        result.status, result.stop_reason = "rate_limited", "rate_limited"
        result.reset_at, result.error = exc.reset_at, str(exc)
    except XApiError as exc:
        result.status, result.stop_reason, result.error = "error", "error", str(exc)
    result.cost = api.meter.as_dict()
    result.total = store.count()
    store.finish_run(run, result.status, pages=result.pages, fetched=result.fetched,
                     new=result.new, stop_reason=result.stop_reason, cost=result.cost,
                     error=result.error)
    return result


def _fill_missing_articles(api: XApi, items: list[reader.Item]) -> int:
    """Look up Article posts whose body did not come inline (standard price, rare)."""
    ids = reader.missing_article_ids(items)
    if not ids:
        return 0
    return reader.fill_articles(items, list(api.tweets(ids)))
