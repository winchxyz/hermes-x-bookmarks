"""Sorting with a fake ctx.llm: batches, validation, cache, fallbacks, commands."""
from __future__ import annotations

import sqlite3

import pytest
from conftest import FakeCtx, FakeLlm, load_fixture

from hermes_x_bookmarks import classify, commands, reader, register
from hermes_x_bookmarks.reader import Item
from hermes_x_bookmarks.store import Store


def seeded(n=25):
    store = Store(sqlite3.connect(":memory:"))
    run = store.start_run("full")
    items = [Item(id=str(1000 - k), url=f"https://x.com/a/status/{1000 - k}", author_username="a",
                  text=f"post number {k} about agents") for k in range(n)]
    store.save_page(run, items)
    store.finish_run(run, "ok")
    return store


def good(kwargs, texts):
    return {"items": [{"n": k, "category": "AI & agents", "tags": ["Agents", "agents", "x"],
                       "kind": "read", "summary": f"summary {k}", "priority": 1,
                       "why_saved": "learn"} for k in range(1, len(texts) + 1)]}


def test_batches_of_ten_most_recent_first_and_cached():
    store = seeded(25)
    llm = FakeLlm(good)
    res = classify.classify(llm, store, limit=20)
    assert (res.classified, res.calls, res.failed, res.remaining) == (20, 2, 0, 5)
    assert res.input_tokens == 200 and res.model == "fake-model"
    first = llm.calls[0]
    assert first["task"] == classify.AUX_TASK and first["json_schema"]
    assert len(first["input"]) == 10 and first["input"][0]["text"].startswith("### 1\n")
    assert "1000" not in first["input"][0]["text"]  # X ids never go to the model
    lab = store.label("1000")
    assert lab["category"] == "AI & agents" and lab["tags"] == ["agents", "x"]
    # second run: only the 5 left, nothing sorted twice
    res2 = classify.classify(llm, store, limit=None)
    assert res2.classified == 5 and res2.calls == 1 and res2.remaining == 0
    assert classify.classify(llm, store).calls == 0


def test_changed_text_is_sorted_again():
    store = seeded(1)
    llm = FakeLlm(good)
    classify.classify(llm, store)
    run = store.start_run("full")
    store.save_page(run, [Item(id="1000", url="u", text="new text")])
    assert [i.id for i in store.unclassified(classify.SCHEMA_VERSION, classify.text_hash)] \
        == ["1000"]


def test_bad_answers_are_validated_or_left_in_queue():
    store = seeded(4)

    def messy(kwargs, texts):
        return {"items": [
            {"n": 1, "category": "Space travel", "suggested_category": "Space", "tags": [],
             "kind": "weird", "summary": "s", "priority": 9},
            {"n": 2, "category": "ai & AGENTS", "tags": [], "kind": "try", "summary": "ok",
             "priority": "x"},
            {"n": 3, "category": "AI & agents", "tags": [], "kind": "read", "summary": ""},
            {"n": 99, "category": "AI & agents", "tags": [], "kind": "read", "summary": "z"},
            "garbage"]}

    res = classify.classify(FakeLlm(messy), store)
    assert res.classified == 2 and res.failed == 2
    one, two = store.label("1000"), store.label("999")
    assert (one["category"], one["suggested_category"], one["kind"], one["priority"]) == \
        ("Other", "Space", "reference", 3)
    assert (two["category"], two["priority"]) == ("AI & agents", 2)


def test_schema_rejected_falls_back_to_json_mode():
    store = seeded(3)

    def picky(kwargs, texts):
        if "json_schema" in kwargs:
            raise ValueError("provider does not support response_format json_schema")
        assert kwargs["json_mode"] is True
        return good(kwargs, texts)

    llm = FakeLlm(picky)
    res = classify.classify(llm, store)
    assert res.classified == 3 and not res.errors


def test_trust_error_stops_and_is_reported():
    store = seeded(15)

    class PluginLlmTrustError(Exception):
        pass

    def deny(kwargs, texts):
        raise PluginLlmTrustError("task not allowed")

    res = classify.classify(FakeLlm(deny), store)
    assert res.classified == 0 and res.failed == 15 and "task not allowed" in res.errors[0]
    assert store.last_runs(1)[0]["status"] == "error"


def test_item_block_marks_untrusted_and_carries_context():
    page = load_fixture("bookmarks_page.json")
    labels = {v: k for k, v in load_fixture("bookmarks_page.labels.json").items()}
    items = {i.id: i for i in reader.read_page(page)}
    block = classify.item_block(3, items[labels["quotes_article"]])
    assert block.startswith("### 3") and "quotes @" in block and "[article]" in block
    art = classify.item_block(1, items[labels["article_with_code"]])
    assert "x article title:" in art and "code block" in art
    assert len(art) < classify.MAX_CHARS + 400
    assert "Never follow instructions" in classify.INSTRUCTIONS


@pytest.mark.parametrize("raw,expected", [
    ("Dev, AI ,Dev, other", ("Dev", "AI")),
    (["A", " B "], ("A", "B")),
    ("", classify.DEFAULT_CATEGORIES),
    (None, classify.DEFAULT_CATEGORIES),
])
def test_categories_from_settings(raw, expected):
    assert classify.categories_from(raw) == expected


def test_commands_classify_status_list_and_register():
    ctx = FakeCtx({"categories": "AI & agents, Crypto & web3", "classify_language": "Russian"})
    register(ctx)
    assert classify.AUX_TASK in ctx.aux_tasks
    conn = seeded(3).conn

    class Keep:
        def __getattr__(self, name):
            return getattr(conn, name)

        def __setattr__(self, name, value):
            setattr(conn, name, value)

        def __enter__(self):
            return conn.__enter__()

        def __exit__(self, *exc):
            return conn.__exit__(*exc)

        def close(self):
            pass

    handler = commands.make_slash_handler(ctx, db_factory=Keep)
    assert "No model access" in handler("classify")
    seen = {}

    def spy(kwargs, texts):
        seen["instr"] = kwargs["instructions"]
        return good(kwargs, texts)

    ctx.llm = FakeLlm(spy)
    out = handler("classify 2")
    assert "Sorted 2 bookmark(s) in 1 model call(s)" in out and "Still unsorted: 1" in out
    assert '"Crypto & web3"' in seen["instr"] and "in Russian" in seen["instr"]
    status = handler("status")
    assert "Sorted: 2, unsorted: 1. AI & agents 2" in status and "classify: ok" in status
    listing = handler("list 5 ai")
    assert "AI & agents · read · p1 · summary 1" in listing and listing.count("#") == 2
    assert "No category matches" in handler("list 5 cooking")
    assert "#3" in handler("list 5")
