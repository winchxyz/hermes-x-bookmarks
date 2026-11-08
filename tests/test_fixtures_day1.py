"""Article detection against anonymised real X responses from the day-1 probe (2026-11-08)."""
from __future__ import annotations

import json

from conftest import FIXTURES

from hermes_x_bookmarks import articles


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


PAGE = load("bookmarks_page.json")
LABELS = {v: k for k, v in load("bookmarks_page.labels.json").items()}
POSTS = {p["id"]: p for p in PAGE["data"]}
INCLUDED = articles.index_by_id(PAGE["includes"]["tweets"])


def post(label):
    return POSTS[LABELS[label]]


def test_article_bookmarks_carry_plain_text_inline():
    for label in ("article_with_code", "article_zero_width"):
        assert articles.has_article_body(post(label)), label
    code = post("article_with_code")["article"]["entities"]["code"]
    assert code and {"code", "language"} <= set(code[0])


def test_quoted_article_found_in_includes():
    p = post("quotes_article")
    quoted = [INCLUDED[q] for q in articles.quoted_ids(p) if q in INCLUDED]
    assert any(articles.has_article_body(q) for q in quoted)


def test_no_card_article_on_real_page():
    # Article posts link to themselves and quoting posts are case (b1): neither is (b2).
    for pid, p in POSTS.items():
        assert articles.card_article_ids(p, INCLUDED) == [], pid
    assert articles.article_link_ids(post("article_with_code"))  # the self link exists


def test_clean_text_on_real_quirks():
    zw = post("article_zero_width")["article"]["plain_text"]
    assert any(ch in zw for ch in "\u200b\u200c\u200d\u2060\ufeff")
    cleaned = articles.clean_text(zw)
    assert not any(ch in cleaned for ch in "\u200b\u200c\u200d\u2060\ufeff")
    styled = post("styled_letters")["note_tweet"]["text"]
    assert any(0x1D400 <= ord(ch) <= 0x1D7FF for ch in styled)
    assert not any(0x1D400 <= ord(ch) <= 0x1D7FF for ch in articles.clean_text(styled))


def test_long_post_and_thread_shapes():
    assert post("long_post_with_entities")["note_tweet"]["text"]
    reply = post("thread_self_reply")
    assert reply["referenced_tweets"][0]["type"] == "replied_to"
    assert reply["conversation_id"] != reply["id"]


def test_post_fields_variant_renames_fields():
    one = load("bookmarks_post_fields_variant.json")["data"][0]
    assert "note_post" in one and "referenced_posts" in one and "edit_history_post_ids" in one
    assert "note_tweet" not in one


def test_article_id_lookup_is_not_found():
    err = load("lookup_article_id_not_found.json")["errors"][0]
    assert err["type"].endswith("resource-not-found")
    assert load("users_me.json")["data"]["username"]
