"""Day-1 spike: ask the live X API the questions the design depends on, keep the raw answers.

``hermes xbm probe`` runs it. Every raw response is saved under
``<HERMES_HOME>/plugin-data/hermes-x-bookmarks/probe/<UTC stamp>/`` (your own data, never
committed); ``report.json`` there holds the answers:

1. Which parameter names work on the bookmarks endpoint: ``tweet.fields`` (old) or ``post.fields``.
2. Whether ``article.plain_text`` comes back (a) on the bookmark itself, (b1) on a quoted Article
   post in ``includes.tweets``, (b2) for the number in an ``x.com/i/article/<n>`` link through
   ``GET /2/tweets?ids=<n>``, and whether asking for ``note_tweet`` too drops it.
3. How many bookmarks a full run returns and what it cost (estimate).
"""
from __future__ import annotations

import datetime as _dt
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from . import articles
from .xapi import (
    EXPANSIONS,
    MEDIA_FIELDS,
    POST_PARAMS,
    TWEET_FIELDS,
    USER_FIELDS,
    XApi,
    XApiError,
)

VARIANT_PAGE = 10
MAX_LOOKUPS = 100

VARIANTS: dict[str, dict[str, str]] = {
    # what the plugin sends today
    "tweet_fields": dict(POST_PARAMS),
    # same plus fields/expansions staff threads use but spec 2.174 does not list
    "tweet_fields_extra": {**POST_PARAMS,
                           "tweet.fields": TWEET_FIELDS + ",card_uri",
                           "expansions": EXPANSIONS + ",referenced_tweets.id.author_id"},
    # spec 2.174 names
    "post_fields": {
        "post.fields": TWEET_FIELDS.replace("note_tweet", "note_post")
                                   .replace("referenced_tweets", "referenced_posts"),
        "expansions": EXPANSIONS.replace("referenced_tweets.id", "referenced_posts"),
        "user.fields": USER_FIELDS, "media.fields": MEDIA_FIELDS},
    # Article without note_tweet: does asking for both drop plain_text?
    "article_only": {"tweet.fields": "id,text,author_id,referenced_tweets,entities,article",
                     "expansions": "referenced_tweets.id"},
}


def _stamp() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def default_out_dir() -> Path:
    from plugins.plugin_storage import plugin_data_dir

    from . import PLUGIN_NAME

    return plugin_data_dir(PLUGIN_NAME) / "probe" / _stamp()


def _save(out: Path, name: str, payload: Any) -> None:
    (out / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _error(exc: XApiError) -> dict[str, Any]:
    return {"status": exc.status, "title": exc.title, "detail": exc.detail, "body": exc.body}


def article_facts(post: Mapping[str, Any] | None) -> dict[str, Any]:
    art = articles.article_of(post)
    if art is None:
        return {"article": False}
    text = str(art.get("plain_text") or "")
    return {"article": True, "keys": sorted(art), "title_len": len(str(art.get("title") or "")),
            "plain_text_len": len(text),
            "zero_width": sum(text.count(c) for c in "\u200b\u200c\u200d\u2060\ufeff"),
            "cover_media_type": type(art.get("cover_media")).__name__}


def describe_page(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Shape facts about one response: which keys came back, Article bodies, long posts."""
    data = [p for p in (payload.get("data") or []) if isinstance(p, dict)]
    inc = articles.index_by_id((payload.get("includes") or {}).get("tweets"))
    keys = sorted({k for p in data for k in p})
    return {
        "count": len(data),
        "post_keys": keys,
        "has_note_tweet_key": "note_tweet" in keys,
        "has_note_post_key": "note_post" in keys,
        "has_referenced_posts_key": "referenced_posts" in keys,
        "includes": sorted((payload.get("includes") or {}).keys()),
        "articles": {p["id"]: article_facts(p) for p in data if articles.article_of(p)},
        "quoted_articles": {q: article_facts(inc.get(q)) for p in data
                            for q in articles.quoted_ids(p) if articles.article_of(inc.get(q))},
        "errors": payload.get("errors"),
    }


def classify(post: Mapping[str, Any], inc: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Short tags so the owner can match the first bookmarks with the test posts they made."""
    tags = []
    if articles.article_of(post):
        tags.append("article(a)")
    if any(articles.article_of(inc.get(q)) for q in articles.quoted_ids(post)):
        tags.append("quotes-article(b1)")
    elif articles.quoted_ids(post):
        tags.append("quote")
    if articles.article_link_ids(post):
        tags.append("article-link(b2)")
    if post.get("note_tweet"):
        tags.append("long")
    if post.get("conversation_id") and post.get("conversation_id") != post.get("id"):
        tags.append("in-thread")
    if (post.get("attachments") or {}).get("media_keys"):
        tags.append("media")
    if articles.url_entities(post) and "article-link(b2)" not in tags:
        tags.append("link")
    return tags or ["plain"]


def run_probe(api: XApi, out: Path, *, max_pages: int = 10,
              log: Callable[[str], None] = print) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"started": _stamp(), "transport": getattr(api.transport, "name", "?")}

    me = api.me()
    _save(out, "me.json", me)
    uid = str(me["id"])
    log(f"signed in as user id {uid}")

    # 1. parameter names and the note_tweet + article question, on the newest bookmarks
    variants: dict[str, Any] = {}
    for name, params in VARIANTS.items():
        query = {**params, "max_results": VARIANT_PAGE}
        try:
            payload = api.get(f"/2/users/{uid}/bookmarks", query, owned=True)
        except XApiError as exc:
            variants[name] = {"ok": False, **_error(exc)}
            log(f"variant {name}: HTTP {exc.status} {exc.title} {exc.detail}")
            continue
        _save(out, f"variant-{name}.json", payload)
        variants[name] = {"ok": True, **describe_page(payload)}
        log(f"variant {name}: ok, {variants[name]['count']} posts")
    report["variants"] = variants

    # 2. full traversal with the plugin's parameters
    pages: list[dict[str, Any]] = []
    stop = "no next_token"
    try:
        for i, payload in enumerate(api.bookmark_pages(uid, max_pages=max_pages), 1):
            _save(out, f"bookmarks-p{i:02d}.json", payload)
            pages.append(payload)
            log(f"bookmarks page {i}: {len(payload.get('data') or [])} posts")
        if pages and (pages[-1].get("meta") or {}).get("next_token"):
            stop = f"max_pages={max_pages}"
    except XApiError as exc:
        stop = f"error HTTP {exc.status} {exc.title}"
        report["traversal_error"] = _error(exc)
    posts = [p for pg in pages for p in (pg.get("data") or []) if isinstance(p, dict)]
    inc: dict[str, dict[str, Any]] = {}
    for pg in pages:
        inc.update(articles.index_by_id((pg.get("includes") or {}).get("tweets")))
    report["traversal"] = {
        "pages": len(pages), "per_page": [len(pg.get("data") or []) for pg in pages],
        "total": len(posts), "unique": len({p.get("id") for p in posts}), "stopped": stop,
        "rate_limit": vars(api.last_rate),
        "first_posts": [{"id": p.get("id"), "created_at": p.get("created_at"),
                         "tags": classify(p, inc)} for p in posts[:12]],
    }

    # 3. what the bookmarks call alone gives for each Article case
    case_a = {p["id"]: article_facts(p) for p in posts if articles.article_of(p)}
    case_b1 = {p["id"]: {q: article_facts(inc.get(q)) for q in articles.quoted_ids(p)
                         if articles.article_of(inc.get(q))}
               for p in posts if any(articles.article_of(inc.get(q))
                                     for q in articles.quoted_ids(p))}
    case_b2 = {p["id"]: {"link_ids": articles.article_link_ids(p),
                         "url_entities": [{k: u.get(k) for k in
                                           ("expanded_url", "unwound_url", "title", "description",
                                            "status") if k in u}
                                          for u in articles.url_entities(p)]}
               for p in posts if articles.article_link_ids(p)}
    report["bookmarks_call"] = {
        "case_a_article": case_a, "case_b1_quoted_article": case_b1,
        "case_b2_article_link": case_b2,
        "long_posts": sum(1 for p in posts if p.get("note_tweet")),
        "in_thread": sum(1 for p in posts if p.get("conversation_id")
                         and p.get("conversation_id") != p.get("id")),
    }

    # 4. GET /2/tweets for what the bookmarks call did not fill, and for every b2 link number
    want: dict[str, str] = {}
    for pid, facts in case_a.items():
        if not facts.get("plain_text_len"):
            want[pid] = "a: re-fetch article"
    for pid, quoted in case_b1.items():
        for qid, facts in quoted.items():
            if not facts.get("plain_text_len"):
                want[qid] = f"b1: quoted article of {pid}"
    for pid, b2 in case_b2.items():
        for n in b2["link_ids"]:
            want.setdefault(n, f"b2: article link in {pid}")
    lookups: dict[str, Any] = {}
    ids = list(want)[:MAX_LOOKUPS]
    if ids:
        try:
            for i, payload in enumerate(api.tweets(ids), 1):
                _save(out, f"lookup-{i:02d}.json", payload)
                got = articles.index_by_id(payload.get("data"))
                errs = {str(e.get("value") or e.get("resource_id") or ""): e
                        for e in (payload.get("errors") or []) if isinstance(e, dict)}
                for n in ids:
                    if n in got:
                        lookups[n] = {"why": want[n], "found": True, **article_facts(got[n])}
                    elif n in errs:
                        lookups[n] = {"why": want[n], "found": False,
                                      "error": {k: errs[n].get(k) for k in ("title", "detail",
                                                                            "type")}}
        except XApiError as exc:
            lookups["_error"] = _error(exc)
    report["lookups"] = lookups
    report["cost"] = api.meter.as_dict()
    report["finished"] = _stamp()
    _save(out, "report.json", report)
    return report


def summary_lines(report: Mapping[str, Any]) -> list[str]:
    lines = []
    for name, v in (report.get("variants") or {}).items():
        if v.get("ok"):
            arts = v.get("articles") or {}
            with_text = sum(1 for f in arts.values() if f.get("plain_text_len"))
            lines.append(f"variant {name}: ok, {v.get('count')} posts, articles {len(arts)} "
                         f"(with plain_text {with_text}), "
                         f"note_tweet key {v.get('has_note_tweet_key')}, "
                         f"note_post key {v.get('has_note_post_key')}")
        else:
            lines.append(f"variant {name}: HTTP {v.get('status')} {v.get('title')} "
                         f"{v.get('detail')}")
    t = report.get("traversal") or {}
    lines.append(f"traversal: {t.get('total')} bookmarks ({t.get('unique')} unique) in "
                 f"{t.get('pages')} pages {t.get('per_page')}; stopped: {t.get('stopped')}")
    for row in t.get("first_posts") or []:
        lines.append(f"  {row['id']}  {row.get('created_at')}  {' '.join(row['tags'])}")
    b = report.get("bookmarks_call") or {}
    a = b.get("case_a_article") or {}
    lines.append(f"(a) article bookmarks: {len(a)}, with plain_text inline: "
                 f"{sum(1 for f in a.values() if f.get('plain_text_len'))}")
    b1 = b.get("case_b1_quoted_article") or {}
    b1_text = sum(1 for q in b1.values() for f in q.values() if f.get("plain_text_len"))
    lines.append(f"(b1) posts quoting an article: {len(b1)}, quoted article with plain_text in "
                 f"includes: {b1_text}")
    b2 = b.get("case_b2_article_link") or {}
    lines.append(f"(b2) posts with an article link: {len(b2)}")
    for n, r in (report.get("lookups") or {}).items():
        if n == "_error":
            lines.append(f"  lookup error: {r}")
            continue
        state = (f"found, article={r.get('article')}, plain_text_len={r.get('plain_text_len')}"
                 if r.get("found") else f"not found ({(r.get('error') or {}).get('title')})")
        lines.append(f"  GET /2/tweets?ids={n} [{r.get('why')}]: {state}")
    lines.append(f"long posts: {b.get('long_posts')}, posts inside a thread: {b.get('in_thread')}")
    c = report.get("cost") or {}
    lines.append(f"cost estimate: ${c.get('usd_estimate')} for {c.get('requests')} requests, "
                 f"{c.get('posts')} posts (expansions billed: {c.get('expansions_billed')})")
    return lines
