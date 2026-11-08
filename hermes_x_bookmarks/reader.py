"""Turn one raw X post (plus its page's ``includes``) into the :class:`Item` the plugin uses.

Body text priority: ``article.plain_text`` > ``note_tweet.text`` > ``text``. Every text goes
through :func:`articles.clean_text`. Field names from both X spellings are accepted
(``note_tweet`` / ``note_post``, ``referenced_tweets`` / ``referenced_posts``).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from . import articles

# body_status values
FULL = "full"                      # the whole body is here
ARTICLE_MISSING = "article_missing"  # an Article without plain_text (lookup may fill it)
CARD_ONLY = "card_only"            # case (b2): Article attached as a card; body not reachable
THREAD_PART = "thread_part"        # one post of a thread; the rest is not fetched (yet)

SELF_LINK_HOSTS = ("x.com/i/article/", "twitter.com/i/article/")


@dataclass
class Item:
    id: str
    url: str
    author_id: str = ""
    author_username: str = ""
    author_name: str = ""
    created_at: str = ""
    lang: str = ""
    text: str = ""                 # the body, after the priority rule and clean-up
    body_source: str = "text"      # article | note | text
    body_status: str = FULL
    article_title: str = ""
    article_text: str = ""
    code: list[dict[str, str]] = field(default_factory=list)
    quoted_id: str = ""
    quoted: dict[str, Any] | None = None
    conversation_id: str = ""
    in_reply_to_id: str = ""
    in_thread: bool = False
    card_article_ids: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    media: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Item:
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in known})


def _get(post: Mapping[str, Any], *names: str) -> Any:
    for n in names:
        if post.get(n) is not None:
            return post[n]
    return None


def _refs(post: Mapping[str, Any], kind: str) -> list[str]:
    refs = _get(post, "referenced_tweets", "referenced_posts") or []
    return [str(r["id"]) for r in refs if isinstance(r, dict) and r.get("type") == kind
            and r.get("id")]


def post_url(post_id: str, username: str = "") -> str:
    return (f"https://x.com/{username}/status/{post_id}" if username
            else f"https://x.com/i/web/status/{post_id}")


def _links(post: Mapping[str, Any], own_id: str) -> list[dict[str, str]]:
    """External links (no t.co, no links to the post itself or its own Article)."""
    out: dict[str, dict[str, str]] = {}
    note = _get(post, "note_tweet", "note_post") or {}
    for holder in (post, note):
        for u in ((holder.get("entities") or {}).get("urls") or []):
            if not isinstance(u, dict):
                continue
            target = str(u.get("unwound_url") or u.get("expanded_url") or u.get("url") or "")
            if not target or f"/status/{own_id}" in target:
                continue
            if any(h in target for h in SELF_LINK_HOSTS) and articles.article_of(post):
                continue
            if "/photo/" in target or "/video/" in target:
                continue  # media permalinks; the media list covers them
            link = {"url": target}
            for k in ("title", "description"):
                if u.get(k):
                    link[k] = articles.clean_text(str(u[k]))
            out.setdefault(target, link)
    return list(out.values())


def _media(post: Mapping[str, Any], media_by_key: Mapping[str, Mapping[str, Any]]
           ) -> list[dict[str, Any]]:
    keys = list((post.get("attachments") or {}).get("media_keys") or [])
    art = articles.article_of(post)
    if art and art.get("cover_media"):
        keys.insert(0, str(art["cover_media"]))
    out = []
    for k in dict.fromkeys(keys):
        m = media_by_key.get(k)
        if not m:
            continue
        entry = {"type": m.get("type", ""), "url": m.get("url") or m.get("preview_image_url") or ""}
        if m.get("alt_text"):
            entry["alt"] = articles.clean_text(str(m["alt_text"]))
        out.append(entry)
    return out


def _quoted_summary(q: Mapping[str, Any], users: Mapping[str, Mapping[str, Any]]
                    ) -> dict[str, Any]:
    user = users.get(str(q.get("author_id") or "")) or {}
    art = articles.article_of(q)
    note = _get(q, "note_tweet", "note_post") or {}
    out: dict[str, Any] = {
        "id": str(q.get("id")),
        "url": post_url(str(q.get("id")), user.get("username", "")),
        "author_username": user.get("username", ""),
        "text": articles.clean_text(note.get("text") or q.get("text") or ""),
    }
    if art:
        out["article_title"] = articles.clean_text(art.get("title") or "")
        out["article_text"] = articles.clean_text(art.get("plain_text") or "")
    return out


def read_post(post: Mapping[str, Any], includes: Mapping[str, Any] | None = None) -> Item:
    inc = includes or {}
    users = articles.index_by_id(inc.get("users"))
    tweets = articles.index_by_id(inc.get("tweets") or inc.get("posts"))
    media_by_key = {str(m.get("media_key")): m for m in (inc.get("media") or [])
                    if isinstance(m, Mapping)}
    pid = str(post.get("id"))
    user = users.get(str(post.get("author_id") or "")) or {}
    item = Item(id=pid, url=post_url(pid, user.get("username", "")),
                author_id=str(post.get("author_id") or ""),
                author_username=user.get("username", ""),
                author_name=articles.clean_text(user.get("name", "")),
                created_at=str(post.get("created_at") or ""), lang=str(post.get("lang") or ""),
                conversation_id=str(post.get("conversation_id") or ""))

    art = articles.article_of(post)
    note = _get(post, "note_tweet", "note_post") or {}
    if art:
        item.article_title = articles.clean_text(art.get("title") or "")
        item.article_text = articles.clean_text(art.get("plain_text") or "")
        item.code = [{"language": str(c.get("language") or ""), "code": str(c.get("code") or "")}
                     for c in ((art.get("entities") or {}).get("code") or [])
                     if isinstance(c, dict)]
        if item.article_text:
            item.text, item.body_source = item.article_text, "article"
        else:
            item.text = articles.clean_text(art.get("preview_text") or post.get("text") or "")
            item.body_source, item.body_status = "article", ARTICLE_MISSING
    elif note.get("text"):
        item.text, item.body_source = articles.clean_text(note["text"]), "note"
    else:
        item.text = articles.clean_text(str(post.get("text") or ""))

    quoted = _refs(post, "quoted")
    if quoted:
        item.quoted_id = quoted[0]
        if quoted[0] in tweets:
            item.quoted = _quoted_summary(tweets[quoted[0]], users)
    replied = _refs(post, "replied_to")
    item.in_reply_to_id = replied[0] if replied else ""
    item.in_thread = bool(item.conversation_id and item.conversation_id != pid)
    if item.in_thread and item.body_status == FULL:
        item.body_status = THREAD_PART

    item.card_article_ids = articles.card_article_ids(post, tweets)
    if item.card_article_ids and item.body_status == FULL:
        item.body_status = CARD_ONLY
    item.links = _links(post, pid)
    item.media = _media(post, media_by_key)
    pm = post.get("public_metrics") or {}
    item.metrics = {k: int(v) for k, v in pm.items() if isinstance(v, int)}
    return item


def read_page(payload: Mapping[str, Any]) -> list[Item]:
    """Every post of a bookmarks (or lookup) page, in the page's order."""
    inc = payload.get("includes") or {}
    return [read_post(p, inc) for p in (payload.get("data") or []) if isinstance(p, Mapping)]


def missing_article_ids(items: list[Item]) -> list[str]:
    """Post ids to look up because an Article body did not come inline (own or quoted)."""
    out = [i.id for i in items if i.body_status == ARTICLE_MISSING]
    out += [i.quoted["id"] for i in items
            if i.quoted and "article_title" in i.quoted and not i.quoted.get("article_text")]
    return list(dict.fromkeys(out))


def fill_articles(items: list[Item], lookups: list[Mapping[str, Any]]) -> int:
    """Patch Article bodies from ``GET /2/tweets`` answers. Returns how many were filled."""
    bodies: dict[str, str] = {}
    for payload in lookups:
        for p in payload.get("data") or []:
            art = articles.article_of(p)
            if art and art.get("plain_text"):
                bodies[str(p.get("id"))] = articles.clean_text(art["plain_text"])
    filled = 0
    for i in items:
        if i.body_status == ARTICLE_MISSING and i.id in bodies:
            i.article_text = i.text = bodies[i.id]
            i.body_status = THREAD_PART if i.in_thread else FULL
            filled += 1
        if i.quoted and i.quoted.get("id") in bodies and not i.quoted.get("article_text"):
            i.quoted["article_text"] = bodies[i.quoted["id"]]
            filled += 1
    return filled
