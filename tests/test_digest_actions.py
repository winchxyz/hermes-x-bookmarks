"""Digest, tasks, skills, the weekly cron job and the agent tools. No network, no Hermes."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

from conftest import FakeCtx, FakeLlm
from test_export import filled_store

from hermes_x_bookmarks import actions, automation, commands, digest, register, tools
from hermes_x_bookmarks.store import Store

OVERVIEW = {"overview": "Mostly agents and a crypto scare.",
            "post_ideas": ["Idea one", "Idea two", "Idea three", "Idea four"]}

SKILL = {"is_procedure": True, "reason": "", "name": "Write A Guide!!", "description":
         "Writes a guide from notes. Use when asked for a guide.", "when_to_use": "When asked.",
         "steps": ["Collect notes", "Outline", "Write"], "pitfalls": ["Too long"],
         "verification": "Read it back."}


def file_db(tmp_path):
    """filled_store() copied to a file, and a factory that opens it again (commands close it)."""
    path = tmp_path / "data.db"
    src = filled_store().conn
    dst = sqlite3.connect(path)
    src.backup(dst)
    dst.close()
    return lambda: sqlite3.connect(path)


def test_digest_numbers_the_best_first_and_saves_them():
    store = filled_store()
    llm = FakeLlm(lambda kw, texts: OVERVIEW)
    res = digest.build(store, llm, language="Russian", about_me="I build agents")
    assert not res.empty and res.new == 3
    assert res.item_ids == ["3", "2", "1"]          # P1, then P2, then unsorted
    text = res.text
    assert "first digest: all 3 stored so far" in text and "Mostly agents" in text
    assert text.index("1. ") < text.index("2. ") < text.index("3. ")
    assert "[P1 · Crypto & web3]" in text and "https://x.com/a/status/3" in text
    assert text.count("- Idea") == 3 and "Idea four" not in text
    assert 'Reply "task 3"' in text
    call = llm.calls[0]
    assert call["task"] == digest.AUX_TASK and "Russian" in call["instructions"]
    assert "I build agents" in call["instructions"]
    assert "never" in call["instructions"]           # posts are data, not instructions
    assert store.last_digest()["item_ids"] == ["3", "2", "1"]


def test_later_digest_counts_new_ones_and_skips_your_own_posts():
    store = filled_store()
    digest.build(store, None)
    store.set_meta("x_username", "@A")              # post 3 is by @a: your own
    res = digest.build(store, None)
    assert ": 3 new" in res.text and res.item_ids == ["2", "1"] and res.new == 3


def test_digest_without_model_or_with_a_failing_model_still_works():
    store = filled_store()
    assert "Worth your time" in digest.build(store, None).text

    def boom(kw, texts):
        raise RuntimeError("model down")

    res = digest.build(store, FakeLlm(boom))
    assert "No overview this time" in res.text and res.item_ids


def test_empty_week_is_marked_empty_and_mentions_open_tasks():
    store = filled_store()
    store.add_task("2")
    later = dt.datetime.now(dt.UTC) + dt.timedelta(days=30)
    res = digest.build(store, None, now=later)
    assert res.empty and "No new X bookmarks" in res.text and "1 open task" in res.text
    assert store.last_digest() is None


def test_task_from_digest_number_link_and_id():
    store = filled_store()
    digest.build(store, None)
    assert "New task" in actions.add_task(store, "#1", "read this weekend")   # #1 = post 3
    assert "New task" in actions.add_task(store, "https://x.com/b/status/2?s=20")
    assert "Task again" in actions.add_task(store, "2")   # digest item #2 = post 2
    listing = actions.list_tasks(store)
    assert "Open tasks (2)" in listing and "read this weekend" in listing
    assert actions.finish_task(store, "1").startswith("Done")   # number from the task list
    assert "Open tasks (1)" in actions.list_tasks(store)


def test_bad_references_explain_themselves():
    store = filled_store()
    for ref, words in (("3", "no digest yet"), ("", "Which bookmark"), ("999999", "No stored")):
        try:
            actions.resolve(store, ref)
        except actions.ActionError as exc:
            assert words.lower() in str(exc).lower()
        else:
            raise AssertionError(ref)
    digest.build(store, None)
    try:
        actions.resolve(store, "9")
    except actions.ActionError as exc:
        assert "1 to 3" in str(exc)


def test_skill_draft_then_save_through_skill_manage():
    store = filled_store()
    digest.build(store, None)
    llm = FakeLlm(lambda kw, texts: SKILL)
    out = actions.draft_skill(store, llm, "2")
    assert 'Draft skill "write-a-guide"' in out and "skill 2 save" in out
    assert llm.calls[0]["task"] == digest.AUX_TASK
    draft = store.skill_draft("2")
    md = draft["content"]
    assert md.startswith("---\nname: write-a-guide\n") and "## Procedure" in md
    assert "1. Collect notes" in md and "## Pitfalls" in md and "x.com/b/status/2" in md

    sent = []

    def dispatch(name, args):
        sent.append((name, args))
        return json.dumps({"success": True, "message": "created"})

    assert "Created skill" in actions.save_skill(store, dispatch, "2")
    assert sent == [("skill_manage", {"action": "create", "name": "write-a-guide",
                                      "content": md})]
    assert "already created" in actions.save_skill(store, dispatch, "2")


def test_skill_staged_for_approval_and_errors():
    store = filled_store()
    digest.build(store, None)
    actions.draft_skill(store, FakeLlm(lambda kw, t: SKILL), "2")
    staged = actions.save_skill(store, lambda n, a: json.dumps(
        {"success": True, "staged": True, "message": "Approve with /skills approve 7"}), "2")
    assert "waiting for your approval" in staged and "/skills approve 7" in staged
    actions.draft_skill(store, FakeLlm(lambda kw, t: SKILL), "1")      # digest #1 = post 3
    failed = actions.save_skill(store, lambda n, a: json.dumps(
        {"success": False, "error": "name taken"}), "1")
    assert "did not create" in failed and "name taken" in failed
    assert store.skill_draft("3")["saved_at"] is None


def test_post_without_a_procedure_gives_no_skill():
    store = filled_store()
    digest.build(store, None)
    out = actions.draft_skill(store, FakeLlm(lambda kw, t: {**SKILL, "is_procedure": False,
                                                              "reason": "It is news."}), "1")
    assert out.startswith("No skill in this one: It is news.")
    assert store.skill_draft("3") is None


class CronCtx(FakeCtx):
    def __init__(self, answers=None):
        super().__init__()
        self.sent: list[tuple[str, dict]] = []
        self.answers = list(answers or [])

    def dispatch_tool(self, name, args, **kw):
        self.sent.append((name, args))
        return json.dumps(self.answers.pop(0) if self.answers else {"success": True})


def test_schedule_creates_a_continuable_cron_job_then_moves_and_removes_it():
    store = filled_store()
    ctx = CronCtx([{"success": True, "job_id": "j1", "schedule": "0 18 * * 0",
                    "next_run_at": "2026-11-15T18:00", "message": "Cron job 'x' created."}])
    out = automation.schedule(store, ctx.dispatch_tool, [])
    assert "every sunday 6pm" in out[0] and "2026-11-15" in out[0]
    name, args = ctx.sent[0]
    assert name == "cronjob_manage" and args["action"] == "create"
    assert args["schedule"] == "every sunday 6pm" and args["attach_to_session"] is True
    assert args["enabled_toolsets"] == ["x_bookmarks"] and "deliver" not in args
    assert "xbm_digest" in args["prompt"] and "[SILENT]" in args["prompt"]
    assert store.get_meta(automation.JOB_META) == "j1"

    automation.schedule(store, ctx.dispatch_tool, ["every", "monday", "9am"])
    assert ctx.sent[1][1] == {"action": "update", "job_id": "j1", "schedule": "every monday 9am"}

    assert "stopped" in automation.unschedule(store, ctx.dispatch_tool)[0]
    assert ctx.sent[2][1] == {"action": "remove", "job_id": "j1"}
    assert store.get_meta(automation.JOB_META) == ""
    assert "No weekly digest" in automation.unschedule(store, ctx.dispatch_tool)[0]


def test_schedule_recreates_a_job_removed_in_hermes_but_keeps_one_on_a_bad_schedule():
    store = filled_store()
    store.set_meta(automation.JOB_META, "old")
    ctx = CronCtx([{"success": False, "error": "Cron job 'old' not found."},
                   {"success": True, "job_id": "new"}])
    automation.schedule(store, ctx.dispatch_tool, [])
    assert [a["action"] for _, a in ctx.sent] == ["update", "create"]
    assert store.get_meta(automation.JOB_META) == "new"
    ctx = CronCtx([{"success": False, "error": "Invalid schedule 'gibberish'"}])
    out = automation.schedule(store, ctx.dispatch_tool, ["gibberish"])
    assert "did not change" in out[0] and store.get_meta(automation.JOB_META) == "new"
    assert automation.schedule(store, None, [])[0].startswith("Scheduling needs Hermes")


def test_chat_commands(tmp_path):
    db = file_db(tmp_path)
    ctx = CronCtx([{"success": True}, {"success": True, "job_id": "j9"}])  # skill, then cron
    ctx.llm = FakeLlm(lambda kw, texts: OVERVIEW if kw["schema_name"] == "bookmark_digest"
                      else SKILL)
    handler = commands.make_slash_handler(ctx, db_factory=db)
    assert "Worth your time" in handler("digest")
    assert "New task" in handler("task 2 try it")
    assert "try it" in handler("tasks")
    assert handler("done 1").startswith("Done")
    assert "Draft skill" in handler("skill 2")
    assert "Created skill" in handler("skill 2 save")
    assert "scheduled" in handler("schedule")
    assert "stopped" in handler("unschedule")
    assert "no digest" not in handler("task 7").lower() and "1 to 3" in handler("task 7")
    assert "digest" in handler("") and "schedule" in commands.USAGE


def test_agent_tools(tmp_path):
    db = file_db(tmp_path)
    ctx = CronCtx()
    ctx.llm = FakeLlm(lambda kw, texts: OVERVIEW if kw["schema_name"] == "bookmark_digest"
                      else SKILL)
    h = tools.make_handlers(ctx, db_factory=db)
    out = json.loads(h["xbm_digest"]({"days": 7}))
    assert out["success"] and not out["empty"] and out["new"] == 3 and "1. " in out["text"]
    out = json.loads(h["xbm_task"]({"action": "add", "item": "3"}))
    assert out["success"] and "New task" in out["text"]
    assert "Open tasks (1)" in json.loads(h["xbm_task"]({"action": "list"}))["text"]
    out = json.loads(h["xbm_skill"]({"action": "draft", "item": "2"}))
    assert "Draft skill" in out["text"]
    out = json.loads(h["xbm_skill"]({"action": "save", "item": "2"}))
    assert "Created skill" in out["text"] and ctx.sent[-1][0] == "skill_manage"
    bad = json.loads(h["xbm_task"]({"action": "add", "item": "42"}))
    assert bad["success"] is False and "1 to 3" in bad["error"]


def test_digest_tool_syncs_first_and_survives_a_sign_in_failure(tmp_path):
    from hermes_x_bookmarks import auth

    def no_sign_in(cfg):
        raise auth.AuthUnavailable("no keys")

    h = tools.make_handlers(CronCtx(), db_factory=file_db(tmp_path), api_factory=no_sign_in)
    out = json.loads(h["xbm_digest"]({"sync": True}))
    assert out["success"] and "no keys" in out["sync"][0] and out["new"] == 3


class BlueprintCtx(FakeCtx):
    def __init__(self):
        super().__init__()
        self.blueprints = {}

    def register_automation_blueprint(self, key, **kw):
        self.blueprints[key] = kw


def test_register_adds_tools_aux_task_and_blueprint():
    ctx = BlueprintCtx()
    register(ctx)
    assert set(ctx.tools) == {"xbm_digest", "xbm_task", "xbm_skill"}
    assert {t["toolset"] for t in ctx.tools.values()} == {"x_bookmarks"}
    for name, t in ctx.tools.items():
        assert t["schema"]["name"] == name
    assert digest.AUX_TASK in ctx.aux_tasks
    bp = ctx.blueprints["weekly-digest"]
    assert bp["schedule_template"] == "{minute} {hour} * * {dow}"
    slots = {s["name"]: s for s in bp["slots"]}
    assert slots["time"]["default"] == "18:00" and slots["day"]["default"] == "sunday"
    assert slots["deliver"]["strict"] is False
    assert bp["prompt_template"] == automation.PROMPT


def test_schema_upgrade_keeps_old_data(tmp_path):
    path = tmp_path / "old.db"
    store = filled_store()
    src = store.conn
    dst = sqlite3.connect(path)
    src.backup(dst)
    dst.execute("DROP TABLE tasks")
    dst.execute("PRAGMA user_version = 3")
    dst.commit()
    dst.close()
    again = Store(sqlite3.connect(path))
    assert again.count() == 3 and again.add_task("2") is True
