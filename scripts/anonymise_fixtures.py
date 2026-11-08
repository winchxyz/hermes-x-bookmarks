"""Turn a `hermes xbm probe` output folder into small, anonymised test fixtures.

    python scripts/anonymise_fixtures.py <probe dir> tests/fixtures

Picks one example of each shape the plugin must handle (Article, quoted Article, long post,
styled letters, thread reply, media + link, expansion errors) and rewrites everything that could
identify a person or reproduce someone's writing:

* every post / user / media id -> a stable fake id (references stay consistent);
* names and handles -> user_N; links -> example.com / t.co fakes;
* all text (posts, long posts, Article bodies, titles, code blocks, alt text) -> filler words of
  similar length that keep the structure the parser cares about: line breaks, URLs, mentions,
  zero-width characters and Mathematical Alphanumeric "styled" letters;
* public metrics -> small fixed numbers.

Only the JSON shape, field names, value types and structure survive. Entity start/end indices are
recomputed for URLs and mentions; other entity indices are dropped.
"""
from __future__ import annotations

import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any

ZERO_WIDTH = {chr(c) for c in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF)}
WORDS = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
         "incididunt ut labore et dolore magna aliqua enim ad minim veniam quis nostrud "
         "exercitation ullamco laboris nisi aliquip ex ea commodo consequat").split()
ID_RE = re.compile(r"\d{15,20}")
URL_RE = re.compile(r"https?://\S+")
TEXT_KEYS = {"text", "plain_text", "preview_text", "title", "content", "description", "alt_text",
             "code", "normalized_text", "tag"}


def dumps(obj: Any) -> str:
    """Readable JSON, but zero-width characters as \\u escapes (Hermes' scanner flags raw ones)."""
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    for ch in ZERO_WIDTH:
        text = text.replace(ch, f"\\u{ord(ch):04x}")
    return text + "\n"


def is_math(ch: str) -> bool:
    return 0x1D400 <= ord(ch) <= 0x1D7FF


def styled(word: str) -> str:
    """Mathematical bold letters (U+1D400 A-Z, U+1D41A a-z) for a plain word."""
    out = []
    for ch in word:
        if "A" <= ch <= "Z":
            out.append(chr(0x1D400 + ord(ch) - ord("A")))
        elif "a" <= ch <= "z":
            out.append(chr(0x1D41A + ord(ch) - ord("a")))
        else:
            out.append(ch)
    return "".join(out)


class Anon:
    def __init__(self) -> None:
        self.ids: dict[str, str] = {}
        self.users: dict[str, str] = {}
        self.links: dict[str, str] = {}
        self.words = itertools.cycle(WORDS)
        self.next_id = itertools.count(1)

    # ids -------------------------------------------------------------------------------------
    def fake_id(self, real: str) -> str:
        if real not in self.ids:
            n = next(self.next_id)
            fake = str(1900000000000000000 + n * 1000003)[: len(real)]
            self.ids[real] = fake.rjust(len(real), "1")
        return self.ids[real]

    def ids_in(self, s: str) -> str:
        return ID_RE.sub(lambda m: self.fake_id(m.group(0)), s)

    def handle(self, real: str) -> str:
        key = real.lower()
        if key not in self.users:
            self.users[key] = f"user_{len(self.users) + 1}"
        return self.users[key]

    # urls ------------------------------------------------------------------------------------
    def url(self, real: str) -> str:
        if real in self.links:
            return self.links[real]
        n = len(self.links) + 1
        m = re.match(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([^/?#]+)(/[^?#]*)?", real)
        if real.startswith("https://t.co/") or real.startswith("http://t.co/"):
            fake = f"https://t.co/fake{n:04d}"
        elif m:
            first, rest = m.group(1), m.group(2) or ""
            head = first if first in ("i", "home", "search", "hashtag") else self.handle(first)
            fake = f"https://x.com/{head}{self.ids_in(rest)}"
        elif real.startswith("https://pbs.twimg.com/") or real.startswith("https://video.twimg.com/"):
            fake = f"https://pbs.twimg.com/media/fake{n:04d}.jpg"
        else:
            fake = f"https://example.com/link/{n}"
        self.links[real] = fake
        return fake

    # text ------------------------------------------------------------------------------------
    def word_like(self, token: str) -> str:
        zw = "".join(ch for ch in token if ch in ZERO_WIDTH)
        core = "".join(ch for ch in token if ch not in ZERO_WIDTH)
        if not core:
            return token
        if URL_RE.fullmatch(core):
            return self.url(core) + zw
        if core.startswith("@") and len(core) > 1:
            name = re.match(r"@(\w+)", core)
            return ("@" + self.handle(name.group(1)) + core[name.end():] if name else core) + zw
        if core.startswith("#"):
            return "#tag" + zw
        trail = re.search(r"[.,:;!?)\]]+$", core)
        tail = trail.group(0) if trail else ""
        word = next(self.words)
        if core[:1].isupper():
            word = word.capitalize()
        if any(is_math(ch) for ch in core):
            word = styled(word)
        return zw[:1] + word + tail + zw[1:]

    def text(self, s: str) -> str:
        parts = re.split(r"(\s+)", s)
        return "".join(p if not p or p.isspace() else self.word_like(p) for p in parts)

    # walk ------------------------------------------------------------------------------------
    def value(self, key: str, v: Any) -> Any:
        if isinstance(v, dict):
            return self.obj(v)
        if isinstance(v, list):
            return [self.value(key, x) for x in v]
        if not isinstance(v, str):
            return v
        if key in ("username",):
            return self.handle(v)
        if key == "name":
            return self.handle(v).replace("user_", "User ")
        if key in ("url", "expanded_url", "unwound_url", "preview_image_url", "profile_image_url"):
            return self.url(v)
        if key == "display_url":
            return self.url("https://" + v.rstrip(chr(0x2026))).split("://", 1)[1][:24]
        if key == "detail":
            return self.ids_in(re.sub(r"@\w+", "@user", v))
        if key in TEXT_KEYS:
            return self.text(v)
        return self.ids_in(v)

    def obj(self, d: dict) -> dict:
        out: dict[str, Any] = {}
        for k, v in d.items():
            if k == "public_metrics" and isinstance(v, dict):
                out[k] = {mk: 1 for mk in v}
            elif k == "variants":
                out[k] = [{"bit_rate": x.get("bit_rate", 0), "content_type": x.get("content_type"),
                           "url": self.url(x.get("url", ""))} for x in v]
            else:
                out[k] = self.value(k, v)
        return out


def reindex(post: dict) -> None:
    """Recompute start/end of URL and mention entities against the rewritten text."""
    for holder in (post, post.get("note_tweet") or {}, post.get("note_post") or {}):
        text = holder.get("text") or ""
        ents = holder.get("entities") or {}
        for kind in list(ents):
            items = ents[kind]
            if not isinstance(items, list):
                continue
            for e in items:
                if not isinstance(e, dict):
                    continue
                needle = e.get("url") if kind == "urls" else (
                    "@" + e["username"] if kind == "mentions" and e.get("username") else None)
                if needle and needle in text:
                    e["start"] = text.index(needle)
                    e["end"] = e["start"] + len(needle)
                else:
                    e.pop("start", None)
                    e.pop("end", None)


def load_pages(src: Path) -> tuple[list[dict], dict[str, list[dict]], list[dict]]:
    posts, includes, errors = [], {"tweets": [], "users": [], "media": []}, []
    for p in sorted(src.glob("bookmarks-p*.json")):
        j = json.loads(p.read_text(encoding="utf-8"))
        posts += j.get("data") or []
        for k in includes:
            includes[k] += (j.get("includes") or {}).get(k) or []
        errors += j.get("errors") or []
    return posts, includes, errors


def pick(posts: list[dict], includes: dict[str, list[dict]]) -> list[tuple[str, dict]]:
    inc = {t["id"]: t for t in includes["tweets"]}

    def art(p):
        return (p.get("article") or {}).get("title")

    def has_math(p):
        s = (p.get("note_tweet") or {}).get("text", "") + p.get("text", "")
        return any(is_math(c) for c in s)

    rules = [
        ("article_with_code",
         lambda p: art(p) and (p["article"].get("entities") or {}).get("code")),
        ("article_zero_width", lambda p: art(p) and any(
            z in p["article"].get("plain_text", "") for z in ZERO_WIDTH)),
        ("quotes_article", lambda p: any(r.get("type") == "quoted" and art(inc.get(r["id"], {}))
                                         for r in p.get("referenced_tweets") or [])),
        ("long_post_with_entities", lambda p: (p.get("note_tweet") or {}).get("entities")),
        ("styled_letters", has_math),
        ("thread_self_reply", lambda p: p.get("in_reply_to_user_id")
         and p.get("in_reply_to_user_id") == p.get("author_id")),
        ("media_and_link", lambda p: (p.get("attachments") or {}).get("media_keys")
         and (p.get("entities") or {}).get("urls") and not art(p)),
        ("plain", lambda p: not art(p) and not p.get("note_tweet") and not p.get("attachments")
         and not p.get("referenced_tweets")),
    ]
    chosen, seen = [], set()
    for label, rule in rules:
        for p in posts:
            if p["id"] not in seen and rule(p):
                chosen.append((label, p))
                seen.add(p["id"])
                break
    return chosen


def page_for(chosen: list[dict], includes: dict[str, list[dict]], errors: list[dict]) -> dict:
    want_t = {r["id"] for p in chosen for r in p.get("referenced_tweets") or []}
    tweets = [t for t in includes["tweets"] if t["id"] in want_t]
    want_u = {p.get("author_id") for p in chosen + tweets}
    want_m = set()
    for p in chosen + tweets:
        want_m.update((p.get("attachments") or {}).get("media_keys") or [])
        a = p.get("article") or {}
        if a.get("cover_media"):
            want_m.add(a["cover_media"])
        want_m.update((a.get("media_entities") or [])[:2])
    users = list({u["id"]: u for u in includes["users"] if u["id"] in want_u}.values())
    media = list({m["media_key"]: m for m in includes["media"]
                  if m["media_key"] in want_m}.values())
    page = {"data": chosen, "includes": {"tweets": tweets, "users": users, "media": media},
            "meta": {"result_count": len(chosen), "next_token": "fakenexttoken0001"}}
    if errors:
        page["errors"] = errors[:2]
    return page


def trim_articles(post: dict, max_lines: int = 60) -> None:
    a = post.get("article")
    if isinstance(a, dict) and a.get("plain_text"):
        lines = a["plain_text"].split("\n")
        if len(lines) > max_lines:
            a["plain_text"] = "\n".join(lines[:max_lines])
        if isinstance(a.get("media_entities"), list):
            a["media_entities"] = a["media_entities"][:2]


def main(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    posts, includes, errors = load_pages(src)
    chosen = pick(posts, includes)
    raw_page = page_for([p for _, p in chosen], includes, errors)
    for p in raw_page["data"] + raw_page["includes"]["tweets"]:
        trim_articles(p)
    anon = Anon()
    page = anon.obj(raw_page)
    page["meta"] = {"result_count": len(page["data"]), "next_token": "fakenexttoken0001"}
    for p in page["data"] + page["includes"]["tweets"]:
        reindex(p)
    (dst / "bookmarks_page.json").write_text(dumps(page), encoding="utf-8")
    labels = {anon.fake_id(p["id"]): label for label, p in chosen}
    (dst / "bookmarks_page.labels.json").write_text(json.dumps(labels, indent=2) + "\n",
                                                    encoding="utf-8")
    # post.fields naming: one long post as the renamed-fields variant returns it
    variant = src / "variant-post_fields.json"
    if variant.exists():
        j = json.loads(variant.read_text(encoding="utf-8"))
        data = j.get("data") or [None]
        one = next((p for p in data if p and p.get("note_post")), data[0])
        if one:
            trim_articles(one)
            fake = anon.obj({"data": [one], "meta": {"result_count": 1}})
            reindex(fake["data"][0])
            (dst / "bookmarks_post_fields_variant.json").write_text(dumps(fake), encoding="utf-8")
    lookup = src / "lookup-01.json"
    if lookup.exists():
        j = json.loads(lookup.read_text(encoding="utf-8"))
        fake = anon.obj({"errors": (j.get("errors") or [])[:1]})
        (dst / "lookup_article_id_not_found.json").write_text(dumps(fake), encoding="utf-8")
    me = src / "me.json"
    if me.exists():
        fake = anon.obj({"data": json.loads(me.read_text(encoding="utf-8"))})
        (dst / "users_me.json").write_text(dumps(fake), encoding="utf-8")
    print("wrote", sorted(p.name for p in dst.glob("*.json")), "labels", list(labels.values()))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
