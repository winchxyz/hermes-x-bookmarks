"""reader.py on the anonymised day-1 page and on small hand-made posts."""
from __future__ import annotations

from conftest import load_fixture

from hermes_x_bookmarks import reader

PAGE = load_fixture("bookmarks_page.json")
LABELS = {v: k for k, v in load_fixture("bookmarks_page.labels.json").items()}
ITEMS = {i.id: i for i in reader.read_page(PAGE)}


def item(label):
    return ITEMS[LABELS[label]]


def test_reads_every_post_in_order():
    assert [i.id for i in reader.read_page(PAGE)] == [p["id"] for p in PAGE["data"]]
    for i in ITEMS.values():
        assert i.text and i.url.startswith("https://x.com/") and i.id in i.url


def test_article_body_wins_and_is_clean():
    a = item("article_with_code")
    assert a.body_source == "article" and a.text == a.article_text and a.article_title
    assert a.code and a.code[0]["code"]
    z = item("article_zero_width")
    assert not any(ch in z.text for ch in "\u200b\u200c\u200d\u2060\ufeff")
    for i in ITEMS.values():  # an Article's own x.com/i/article link is not an external link
        if i.article_title:
            assert not any("/i/article/" in link["url"] for link in i.links)


def test_quoted_article_and_long_post():
    q = item("quotes_article")
    assert q.quoted_id and q.quoted and q.quoted["article_title"] and q.quoted["article_text"]
    long_post = item("long_post_with_entities")
    assert long_post.body_source == "note" and len(long_post.text) > 280


def test_styled_letters_and_thread_and_media():
    assert not any(0x1D400 <= ord(ch) <= 0x1D7FF for ch in item("styled_letters").text)
    t = item("thread_self_reply")
    assert t.in_thread and t.in_reply_to_id and t.body_status == reader.THREAD_PART
    m = item("media_and_link")
    assert m.media and all(x["url"] for x in m.media)
    assert item("plain").body_status == reader.FULL and item("plain").body_source == "text"


def test_post_fields_spelling_is_read_too():
    variant = load_fixture("bookmarks_post_fields_variant.json")
    (one,) = reader.read_page(variant)
    assert one.body_source == "note" and one.text


def test_card_article_marks_card_only():
    post = {"id": "5", "text": "see", "conversation_id": "5",
            "entities": {"urls": [{"expanded_url": "https://x.com/i/article/123456789",
                                   "title": "Card title"}]}}
    i = reader.read_post(post)
    assert i.card_article_ids == ["123456789"] and i.body_status == reader.CARD_ONLY
    assert i.links == [{"url": "https://x.com/i/article/123456789", "title": "Card title"}]


def test_missing_article_body_is_filled_from_lookup():
    own = {"id": "7", "text": "t", "article": {"title": "Own", "preview_text": "pre"}}
    quoter = {"id": "8", "text": "q", "referenced_tweets": [{"type": "quoted", "id": "9"}]}
    items = reader.read_page({"data": [own, quoter],
                              "includes": {"tweets": [{"id": "9", "article": {"title": "Q"}}]}})
    assert items[0].body_status == reader.ARTICLE_MISSING and items[0].text == "pre"
    assert reader.missing_article_ids(items) == ["7", "9"]
    lookups = [{"data": [{"id": "7", "article": {"title": "Own", "plain_text": "Body 7"}},
                         {"id": "9", "article": {"title": "Q", "plain_text": "Body 9"}}]}]
    assert reader.fill_articles(items, lookups) == 2
    assert items[0].text == "Body 7" and items[0].body_status == reader.FULL
    assert items[1].quoted["article_text"] == "Body 9"


def test_item_round_trip():
    i = item("article_with_code")
    assert reader.Item.from_dict(i.to_dict()) == i
