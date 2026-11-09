"""Obsidian, Notion and Google Docs exports, with fake HTTP and a temporary vault."""
from __future__ import annotations

import json

from test_export import filled_store

from hermes_x_bookmarks import commands, gdocs, notion, obsidian
from hermes_x_bookmarks.classify import Label

# Obsidian -------------------------------------------------------------------------------------


def test_vault_from_obsidian_json_prefers_the_open_one(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    cfg = tmp_path / "obsidian.json"
    cfg.write_text(json.dumps({"vaults": {
        "1": {"path": str(a), "ts": 9, "open": False},
        "2": {"path": str(b), "ts": 1, "open": True}}}), encoding="utf-8")
    assert obsidian.vault_from_obsidian(cfg) == b
    assert obsidian.find_vault("", cfg) == b
    assert obsidian.find_vault(str(a), cfg) == a


def test_no_vault_is_a_clear_error(tmp_path):
    try:
        obsidian.find_vault("", tmp_path / "missing.json")
    except obsidian.VaultNotFound as exc:
        assert "obsidian_vault" in str(exc)
    else:
        raise AssertionError("expected VaultNotFound")


def test_notes_created_then_only_plugin_keys_updated(tmp_path):
    store = filled_store()
    res = obsidian.export(store, vault=str(tmp_path))
    folder = tmp_path / "X Bookmarks"
    assert res.created == 3 and (folder / obsidian.BASE_FILE).exists()
    notes = obsidian.index_notes(folder)
    assert set(notes) == {"1", "2", "3"}
    guide = notes["2"].read_text(encoding="utf-8")
    assert guide.startswith("---\ntweet_id: \"2\"\n") and 'status: "inbox"' in guide
    assert "  - \"ai\"" in guide and "# Big [guide] *bold*" in guide
    assert "An article body" in guide

    # the user edits status, adds a key and writes in the body; then the label changes
    edited = guide.replace('status: "inbox"', 'status: "done"\nrating: 5') + "\nMy note.\n"
    notes["2"].write_text(edited, encoding="utf-8")
    notes["2"].rename(folder / "renamed.md")
    store.save_label("2", "h", 3, Label("Coding & dev tools", ["python"], "read", "new", 1))
    res = obsidian.export(store, vault=str(tmp_path))
    assert (res.created, res.updated, res.unchanged) == (0, 1, 2)
    text = (folder / "renamed.md").read_text(encoding="utf-8")
    assert 'category: "Coding & dev tools"' in text and '"python"' in text
    assert 'status: "done"' in text and "rating: 5" in text and "My note." in text
    assert '"ai"' not in text


def test_note_names_are_safe(tmp_path):
    taken: set[str] = set()
    c = {"title": 'a/b:c*?"<>|#^[x]', "summary": "", "text": "", "id": "9"}
    name = obsidian.note_name(c, taken)
    assert not set('/\\:*?"<>|#^[]') & set(name) and name.endswith(".md")
    assert obsidian.note_name(c, taken).endswith("(9).md")


# Notion ---------------------------------------------------------------------------------------


class FakeNotion:
    def __init__(self, fail=None):
        self.calls: list[tuple[str, str, object]] = []
        self.fail = fail or {}
        self.pages = 0

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        key = (method, path.split("/")[1] if "/" in path else path)
        if key in self.fail:
            status, data = self.fail.pop(key)
            return status, {"Retry-After": "0"}, data
        if method == "POST" and path == "/databases":
            return 200, {}, {"id": "db1", "url": "https://app.notion.com/p/db1",
                             "data_sources": [{"id": "ds1"}]}
        if method == "GET" and path.startswith("/data_sources/"):
            return 200, {}, {"id": "ds1", "properties": {
                "Category": {"id": "cat"}, "Status": {"id": "st"}}}
        if method == "POST" and path == "/views":
            return 200, {}, {"id": "v"}
        if method == "POST" and path == "/pages":
            self.pages += 1
            return 200, {}, {"id": f"page{self.pages}"}
        if method == "PATCH":
            return 200, {}, {"id": path.split("/")[-1]}
        return 404, {}, {"code": "object_not_found", "message": "?"}


def api_for(fake):
    return notion.NotionApi(fake, sleep=lambda s: None, clock=lambda: 0.0)


def test_page_id_from_url():
    want = "0123abcd-0123-4567-89ab-0123456789ab"
    assert notion.page_id_from("https://www.notion.so/me/X-Bookmarks-0123abcd0123456789ab0123456789ab"
                               "?pvs=4") == want
    assert notion.page_id_from(want) == want
    assert notion.page_id_from("not a page") == ""


def test_notion_creates_database_views_and_pages_then_skips_unchanged():
    store = filled_store()
    fake = FakeNotion()
    page = "https://www.notion.so/X-0123abcd0123456789ab0123456789ab"
    res = notion.export(store, parent=page, categories=["AI & agents"], api=api_for(fake))
    assert res.new_database and res.created == 3 and not res.errors
    db = next(b for m, p, b in fake.calls if p == "/databases")
    props = db["initial_data_source"]["properties"]
    assert props["Post ID"] == {"rich_text": {}} and "Status" in props
    views = [b for m, p, b in fake.calls if p == "/views"]
    assert [v["name"] for v in views] == ["By category", "By status"]
    created = [b for m, p, b in fake.calls if p == "/pages"]
    assert all("Status" not in b["properties"] for b in created)  # the user's column
    assert created[0]["parent"] == {"type": "data_source_id", "data_source_id": "ds1"}
    assert created[0]["properties"]["Post ID"]["rich_text"][0]["text"]["content"] == "3"

    fake.calls.clear()
    res = notion.export(store, parent=page, categories=["AI & agents"], api=api_for(fake))
    assert res.unchanged == 3 and res.created == 0
    assert [p for _, p, _ in fake.calls] == ["/data_sources/ds1"]

    store.save_label("2", "h", 3, Label("AI & agents", ["ai"], "try", "changed", 1))
    fake.calls.clear()
    res = notion.export(store, parent=page, categories=[], api=api_for(fake))
    assert res.updated == 1
    patch = next(b for m, p, b in fake.calls if m == "PATCH")
    assert "Status" not in patch["properties"] and "children" not in patch


def test_notion_page_deleted_by_user_is_not_recreated():
    store = filled_store()
    fake = FakeNotion()
    page = "0123abcd0123456789ab0123456789ab"
    notion.export(store, parent=page, categories=[], api=api_for(fake))
    store.save_label("3", "h", 3, Label("AI & agents", [], "read", "x", 2))
    fake.fail[("PATCH", "pages")] = (400, {"code": "validation_error",
                                           "message": "Can't edit block that is archived."})
    res = notion.export(store, parent=page, categories=[], api=api_for(fake))
    assert res.skipped_deleted == 1 and res.created == 0
    res = notion.export(store, parent=page, categories=[], api=api_for(fake))
    assert res.skipped_deleted == 1 and res.created == 0


def test_notion_retries_429_and_limits_per_run():
    store = filled_store()
    fake = FakeNotion(fail={("POST", "databases"): (429, {"code": "rate_limited"})})
    res = notion.export(store, parent="0123abcd0123456789ab0123456789ab", categories=[],
                        api=api_for(fake), limit=2)
    assert res.created == 2 and res.left == 1
    assert [p for _, p, _ in fake.calls].count("/databases") == 2


def test_notion_unshared_page_explains_what_to_do():
    store = filled_store()
    fake = FakeNotion(fail={("POST", "databases"): (404, {"code": "object_not_found"})})
    res = notion.export(store, parent="0123abcd0123456789ab0123456789ab", categories=[],
                        api=api_for(fake))
    assert "Connections" in res.lines()[-1]


def test_notion_without_token_or_page():
    store = filled_store()
    assert "notion_page" in notion.export(store, parent="", categories=[]).errors[0]
    res = notion.export(store, parent="0123abcd0123456789ab0123456789ab", categories=[])
    assert notion.TOKEN_ENV in res.errors[0]


def test_long_text_is_chunked():
    chunks = notion.rich("x" * 4500)
    assert [len(c["text"]["content"]) for c in chunks] == [2000, 2000, 500]


# Google Docs ----------------------------------------------------------------------------------


class FakeDocs:
    def __init__(self, existing_end=None):
        self.calls: list[tuple[str, str, object]] = []
        self.existing_end = existing_end

    def __call__(self, method, url, body):
        self.calls.append((method, url, body))
        if method == "GET":
            if self.existing_end is None:
                return 404, {"error": {"message": "not found"}}
            return 200, {"body": {"content": [{"endIndex": 1}, {"endIndex": self.existing_end}]}}
        if url == gdocs.DOCS:
            return 200, {"documentId": "doc1"}
        return 200, {}


def test_gdocs_creates_then_rewrites_same_document():
    store = filled_store()
    fake = FakeDocs()
    res = gdocs.export(store, request=fake)
    assert res.new_document and res.url.endswith("/doc1/edit") and res.count == 3
    first = fake.calls[1][2]["requests"]
    text = first[0]["insertText"]["text"]
    assert "Big [guide] *bold*" in text and "AI & agents (1)" in text
    assert first[0]["insertText"]["location"] == {"index": 1}
    styles = [r for _, u, b in fake.calls[2:] for r in b["requests"]]
    links = [r["updateTextStyle"] for r in styles
             if "link" in r.get("updateTextStyle", {}).get("textStyle", {})]
    assert any(s["textStyle"]["link"]["url"] == "https://x.com/b/status/2" for s in links)

    fake2 = FakeDocs(existing_end=500)
    res = gdocs.export(store, request=fake2)
    assert not res.new_document
    first = fake2.calls[1][2]["requests"]
    assert first[0] == {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": 499}}}


def test_gdocs_indexes_count_utf16():
    doc = gdocs.DocBuilder()
    doc.text("\U0001f600", bold=True)
    doc.text("ab", link="https://x.com")
    ranges = [r["updateTextStyle"]["range"] for r in doc.styles]
    assert ranges == [{"startIndex": 1, "endIndex": 3}, {"startIndex": 3, "endIndex": 5}]


def test_gdocs_not_signed_in_outside_hermes():
    res = gdocs.export(filled_store())
    assert res.errors and "hermes auth add hermes-x-bookmarks:google" in res.errors[0]


# command --------------------------------------------------------------------------------------


def test_parse_targets():
    pt = commands.parse_targets
    assert pt([]) == (["desktop"], "", [])
    assert pt([], "notion, obsidian") == (["notion", "obsidian"], "", [])
    assert pt(["google", "vault"]) == (["gdocs", "obsidian"], "", [])
    url = "https://www.notion.so/X-0123abcd0123456789ab0123456789ab"
    assert pt(["notion", url]) == (["notion"], url, [])
    assert pt(["all"])[0] == ["desktop", "obsidian", "notion", "gdocs"]
    assert pt(["dropbox"])[2] == ["dropbox"]


def test_export_command_runs_each_target_and_keeps_going(tmp_path):
    store = filled_store()
    lines = commands.do_export(store, {"obsidian_vault": str(tmp_path / "nope")},
                               ["obsidian", "desktop"])
    text = "\n".join(lines)
    assert "obsidian export failed" in text.lower() or "does not exist" in text
    lines = commands.do_export(store, {"obsidian_vault": str(tmp_path), "export_dir":
                                       str(tmp_path / "desk")}, ["obsidian", "desktop"])
    text = "\n".join(lines)
    assert "Obsidian: 3 new note(s)" in text and "Exported 3 bookmarks" in text
