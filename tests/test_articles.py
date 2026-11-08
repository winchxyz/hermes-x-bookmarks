"""Article detection for cases (a), (b1), (b2) and text clean-up."""
from __future__ import annotations

from hermes_x_bookmarks import articles


def test_case_a_article_on_the_post():
    post = {"id": "1", "article": {"title": "T", "plain_text": "Body"}}
    assert articles.article_of(post)["title"] == "T"
    assert articles.has_article_body(post)
    assert not articles.has_article_body({"id": "2", "article": {"title": "T"}})
    assert articles.article_of({"id": "3"}) is None


def test_case_b1_quoted_ids():
    post = {"referenced_tweets": [{"type": "replied_to", "id": "9"}, {"type": "quoted", "id": "7"}]}
    assert articles.quoted_ids(post) == ["7"]


def test_case_b2_article_links_in_entities_and_long_post():
    post = {
        "entities": {"urls": [
            {"url": "https://t.co/a", "expanded_url": "https://x.com/i/article/1234567890123"},
            {"url": "https://t.co/b", "expanded_url": "https://example.com/x/article/1"},
        ]},
        "note_tweet": {"entities": {"urls": [
            {"expanded_url": "https://twitter.com/some_user/article/99999"},
            {"expanded_url": "https://x.com/i/article/1234567890123"},
        ]}},
    }
    assert articles.article_link_ids(post) == ["1234567890123", "99999"]


def test_clean_text_strips_zero_width_and_folds_math_letters():
    styled = "\U0001d401\U0001d428\U0001d425\U0001d41d"  # MATHEMATICAL BOLD "Bold"
    assert articles.clean_text(f"a\u200bb\ufeff {styled} Привет") == "ab Bold Привет"
