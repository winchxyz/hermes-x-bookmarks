"""Notion export through Hermes' Notion connector (ctx.call_mcp), with a fake MCP server."""
from __future__ import annotations

import json

from test_export import filled_store

from hermes_x_bookmarks import commands, notion, notion_mcp
from hermes_x_bookmarks.classify import Label

PAGE = "https://app.notion.com/p/X-0123abcd0123456789ab0123456789ab"
DS = "11111111-2222-3333-4444-555555555555"
DB = "99999999aaaabbbbccccdddddddddddd"


class FakeMcp:
    """Answers like Hermes' call_mcp envelope around the hosted Notion MCP server."""

    def __init__(self, fail=None, ids=True):
        self.calls: list[tuple[str, str, dict]] = []
        self.fail = dict(fail or {})
        self.ids = ids
        self.pages = 0
        self.gone: set[str] = set()

    def __call__(self, server, tool, arguments=None, timeout=30):
        self.calls.append((server, tool, arguments))
        if tool in self.fail:
            err = self.fail.pop(tool)
            if isinstance(err, Exception):
                raise err
            return {"ok": False, "error": err}
        if tool == "notion-fetch":
            return {"ok": True, "result": f"<data-source url=\"collection://{DS}\">...</data-source>"}
        if tool == "notion-create-database":
            return {"ok": True, "result": (
                f"Created database <database url=\"https://www.notion.so/{DB}\">X Bookmarks"
                f"</database> with <data-source url=\"collection://{DS}\"></data-source>")}
        if tool == "notion-create-view":
            return {"ok": True, "result": "view created"}
        if tool == "notion-create-pages":
            pages = []
            for _ in arguments["pages"]:
                self.pages += 1
                pid = f"{self.pages:08d}-0000-0000-0000-000000000000"
                pages.append({"id": pid, "url": f"https://www.notion.so/{pid.replace('-', '')}"})
            body = {"pages": pages} if self.ids else {"note": "created"}
            return {"ok": True, "result": json.dumps(body)}
        if tool == "notion-update-page":
            if arguments["page_id"] in self.gone:
                return {"ok": False, "error": "Could not find page: it is in the trash"}
            return {"ok": True, "result": json.dumps({"page_id": arguments["page_id"]})}
        return {"ok": False, "error": f"unknown tool {tool}"}

    def tools(self):
        return [t for _, t, _ in self.calls]


def run(store, fake, **kw):
    return notion_mcp.export(store, parent=PAGE, categories=["AI & agents", "Coding & dev tools"],
                             call_mcp=fake, **kw)


def test_creates_database_boards_and_pages_in_one_batch():
    store = filled_store()
    fake = FakeMcp()
    res = run(store, fake)
    assert res.new_database and res.created == 3 and not res.errors, res.lines()
    assert fake.tools() == ["notion-create-database", "notion-create-view", "notion-create-view",
                            "notion-create-pages"]
    assert all(s == "notion" for s, _, _ in fake.calls)
    ddl = fake.calls[0][2]["schema"]
    assert '"Status" STATUS(' in ddl and "'AI & agents':blue" in ddl and '"URL" URL' in ddl
    assert fake.calls[0][2]["parent"] == {"type": "page_id",
                                          "page_id": "0123abcd-0123-4567-89ab-0123456789ab"}
    views = [a for _, t, a in fake.calls if t == "notion-create-view"]
    assert views[0]["database_id"] == "99999999-aaaa-bbbb-cccc-dddddddddddd"
    assert views[0]["configure"].startswith('GROUP BY "Category"')
    assert views[1]["configure"] == 'GROUP BY "Status" BY OPTION'
    create = fake.calls[-1][2]
    assert create["parent"] == {"type": "data_source_id", "data_source_id": DS}
    props = [p["properties"] for p in create["pages"]]
    assert all("Status" not in p for p in props)  # the user's column
    first = props[0]
    assert first["Post ID"] == "3" and first["Article"] in ("__YES__", "__NO__")
    assert "userDefined:URL" in first and "URL" not in first
    assert res.url == f"https://www.notion.so/{DB}"
    assert store.get_meta("notion_data_source_id") == DS


def test_second_run_sends_nothing_and_changes_go_through_update_properties():
    store = filled_store()
    fake = FakeMcp()
    run(store, fake)
    fake.calls.clear()
    res = run(store, fake)
    assert res.unchanged == 3 and fake.tools() == ["notion-fetch"]

    store.save_label("2", "h", 3, Label("Coding & dev tools", ["python"], "try", "changed", 1))
    fake.calls.clear()
    res = run(store, fake)
    assert res.updated == 1 and fake.tools() == ["notion-fetch", "notion-update-page"]
    upd = fake.calls[-1][2]
    assert upd["command"] == "update_properties" and "Status" not in upd["properties"]
    assert upd["properties"]["Category"] == "Coding & dev tools"
    assert upd["properties"]["Tags"] == []  # "python" is not an option of this database


def notion_400(prop, bad, allowed):
    """The error exactly as the hosted Notion MCP passes it through Hermes (JSON in JSON)."""
    listed = ", ".join(f'"{a}"' for a in allowed)
    body = json.dumps({"object": "error", "status": 400, "code": "validation_error",
                       "message": f'pages[0]: Invalid multi_select value for property "{prop}": '
                                  f'"{bad}". Value must be one of the following: {listed}'})
    return json.dumps({"name": "APIResponseError", "code": "validation_error", "status": 400,
                       "headers": {}, "body": body})


def test_unknown_tags_are_learned_from_notions_answer_and_left_out():
    store = filled_store()
    store.set_meta("notion_parent", "0123abcd-0123-4567-89ab-0123456789ab")
    store.set_meta("notion_data_source_id", DS)  # a database the plugin did not seed
    fake = FakeMcp(fail={"notion-create-pages": notion_400("Tags", "grok-bots", ["ai", "x"])})
    res = run(store, fake)
    assert res.created == 3 and not res.errors, res.lines()
    retry = fake.calls[-1][2]["pages"]
    assert all(set(p["properties"]["Tags"]) <= {"ai", "x"} for p in retry)
    assert json.loads(store.get_meta("notion_mcp_options"))["options"]["Tags"] == ["ai", "x"]


def test_error_text_and_database_url_are_clean():
    detail = notion_400("Tags", "a", ["b"])
    assert notion_mcp.notion_message(detail).startswith("pages[0]: Invalid multi_select")
    assert notion_mcp.allowed_options(detail) == ("Tags", ["b"])
    two = notion_400("Tags", "a", ["b", "c d"])
    assert notion_mcp.allowed_options(two) == ("Tags", ["b", "c d"])
    clean = notion_mcp.notion_message(notion_400("Category", "z", ["AI", "Other"]))
    assert notion_mcp.allowed_options(clean) == ("Category", ["AI", "Other"])
    m = notion_mcp.NOTION_URL.search('{"url":"https://app.notion.com/p/cde1c5cf10304b62a220d7d5a84907e0}}')
    assert m.group(0) == "https://app.notion.com/p/cde1c5cf10304b62a220d7d5a84907e0"


def test_page_deleted_in_notion_is_left_out():
    store = filled_store()
    fake = FakeMcp()
    run(store, fake)
    pid = store.export_map(f"notion:{DS}")["3"][0]
    fake.gone.add(pid)
    store.save_label("3", "h", 3, Label("AI & agents", [], "read", "x", 2))
    res = run(store, fake)
    assert res.skipped_deleted == 1 and res.created == 0
    res = run(store, fake)
    assert res.skipped_deleted == 1 and "notion-update-page" not in fake.tools()[-1:]


def test_not_allowlisted_or_not_connected_explains_setup():
    store = filled_store()
    fake = FakeMcp(fail={"notion-create-database": PermissionError("not in mcp_allowlist")})
    res = run(store, fake)
    assert res.unavailable and "mcp_allowlist" in "\n".join(res.lines())
    fake = FakeMcp(fail={"notion-create-database": "MCP server 'notion' is not connected"})
    res = run(store, fake)
    assert res.unavailable and "hermes mcp install notion" in "\n".join(res.lines())


def test_answer_without_page_ids_falls_back_to_one_page_per_call():
    store = filled_store()
    fake = FakeMcp(ids=False)
    res = run(store, fake)
    assert res.created == 3 and res.notes
    assert fake.tools().count("notion-create-pages") == 1  # all 3 fit one batch


def test_limit_and_markdown_escaping():
    store = filled_store()
    fake = FakeMcp()
    res = run(store, fake, limit=2)
    assert res.created == 2 and res.left == 1
    md = notion_mcp.page_markdown
    assert notion_mcp.escape("# $5 <b> *x*") == "\\# \\$5 \\<b\\> \\*x\\*"
    assert notion_mcp.escape("- item\n1. one") == "\\- item\n\\1. one"
    assert md  # page_markdown is exercised through the export above
    content = fake.calls[-1][2]["pages"][0]["content"]
    assert "<bookmark source=\"https://x.com/" in content


def test_both_routes_share_state():
    store = filled_store()
    run(store, FakeMcp())
    target = f"notion:{DS}"
    assert len(store.export_map(target)) == 3
    from test_destinations import FakeNotion, api_for

    rest = FakeNotion()
    store.set_meta("notion_data_source_id", DS)
    rest_api = api_for(rest)
    res = notion.export(store, parent=PAGE, categories=[], api=rest_api)
    assert res.unchanged == 3 and res.created == 0


# command routing ------------------------------------------------------------------------------


class Ctx:
    def __init__(self, call_mcp=None):
        self.config: dict = {}
        if call_mcp is not None:
            self.call_mcp = call_mcp

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def set_config(self, key, value):
        self.config[key] = value


def test_export_command_uses_connector_and_saves_page():
    store = filled_store()
    fake = FakeMcp()
    ctx = Ctx(fake)
    text = "\n".join(commands.do_export(store, {}, ["notion", PAGE], ctx=ctx))
    assert "Notion: 3 new page(s)" in text and ctx.config["notion_page"] == PAGE


def test_export_command_falls_back_to_token(monkeypatch):
    from hermes_x_bookmarks import secrets

    store = filled_store()
    fake = FakeMcp(fail={"notion-create-database": PermissionError("no")})
    seen = {}

    def fake_export(store, **kw):
        seen.update(kw)
        return notion.NotionResult(created=3)

    monkeypatch.setattr(secrets, "get", lambda name, environ=None: "tok")
    monkeypatch.setattr(notion, "export", fake_export)
    text = "\n".join(commands.do_export(store, {"notion_page": PAGE}, ["notion"], ctx=Ctx(fake)))
    assert seen["token"] == "tok" and "XBM_NOTION_TOKEN was used" in text


def test_export_command_without_connector_or_token(monkeypatch):
    from hermes_x_bookmarks import secrets

    monkeypatch.setattr(secrets, "get", lambda name, environ=None: "")
    text = "\n".join(commands.do_export(filled_store(), {"notion_page": PAGE}, ["notion"],
                                        ctx=Ctx()))
    assert "hermes mcp install notion" in text and "XBM_NOTION_TOKEN" in text
