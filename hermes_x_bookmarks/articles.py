"""X Articles: find them in a post and pick the body text.

Three ways a bookmark carries an Article:

* (a)  the bookmarked post is the Article: ``article.title`` on the post itself;
* (b1) the post quotes an Article post: the quoted post (``includes.tweets``) has ``article.title``;
* (b2) the post links an Article as its card: an ``x.com/i/article/<n>`` or
  ``x.com/<user>/article/<n>`` URL in ``entities.urls``.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

ARTICLE_URL = re.compile(
    r"^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/(?:i|[A-Za-z0-9_]{1,15})/articles?/(\d{5,25})",
    re.IGNORECASE)

ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))


def article_of(post: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The post's ``article`` object when it is an Article (has a title), else None."""
    art = (post or {}).get("article")
    if isinstance(art, dict) and (art.get("title") or art.get("plain_text")):
        return art
    return None


def has_article_body(post: Mapping[str, Any] | None) -> bool:
    art = article_of(post)
    return bool(art and str(art.get("plain_text") or "").strip())


def url_entities(post: Mapping[str, Any]) -> list[dict[str, Any]]:
    """URL entities of the post and of its long-post (``note_tweet``) body."""
    out: list[dict[str, Any]] = []
    for holder in (post, post.get("note_tweet") or {}):
        for u in ((holder.get("entities") or {}).get("urls") or []):
            if isinstance(u, dict):
                out.append(u)
    return out


def article_link_ids(post: Mapping[str, Any]) -> list[str]:
    """Numbers from Article links in the post (case b2), in order, without duplicates."""
    found: list[str] = []
    for u in url_entities(post):
        for key in ("expanded_url", "unwound_url", "url"):
            m = ARTICLE_URL.match(str(u.get(key) or ""))
            if m:
                found.append(m.group(1))
                break
    return list(dict.fromkeys(found))


def card_article_ids(post: Mapping[str, Any],
                     included: Mapping[str, Mapping[str, Any]] | None = None) -> list[str]:
    """Case (b2) only: Article links on a post that is not itself an Article and does not quote one.

    Every Article post links to its own ``x.com/i/article/<n>``, and a quoted Article is case (b1),
    so both are excluded. ``<n>`` is an article id, not a post id: it cannot be looked up.
    """
    if article_of(post):
        return []
    inc = included or {}
    if any(article_of(inc.get(q)) for q in quoted_ids(post)):
        return []
    return article_link_ids(post)


def quoted_ids(post: Mapping[str, Any]) -> list[str]:
    return [str(r.get("id")) for r in (post.get("referenced_tweets") or [])
            if isinstance(r, dict) and r.get("type") == "quoted" and r.get("id")]


def index_by_id(posts: Iterable[Mapping[str, Any]] | None) -> dict[str, dict[str, Any]]:
    return {str(p.get("id")): dict(p) for p in (posts or []) if isinstance(p, Mapping)}


def clean_text(text: str) -> str:
    """Drop zero-width characters and fold Mathematical Alphanumeric bold/italic to plain letters.

    Zero-width characters can trip Hermes' prompt-injection scanner; NFKC turns U+1D400-U+1D7FF
    styled letters and digits into ASCII and leaves other scripts alone.
    """
    text = (text or "").translate(ZERO_WIDTH)
    if any(0x1D400 <= ord(ch) <= 0x1D7FF for ch in text):
        text = "".join(unicodedata.normalize("NFKC", ch) if 0x1D400 <= ord(ch) <= 0x1D7FF else ch
                       for ch in text)
    return text
