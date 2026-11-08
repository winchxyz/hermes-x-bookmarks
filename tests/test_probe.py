"""The day-1 probe answers its questions from scripted X responses and saves every raw answer."""
from __future__ import annotations

import json

from conftest import FakeTransport

from hermes_x_bookmarks import cli, probe
from hermes_x_bookmarks.xapi import XApi

ARTICLE = {"id": "100", "text": "https://t.co/x", "conversation_id": "100",
           "article": {"title": "My article", "plain_text": "Para one\n\u200bPara two"}}
QUOTER = {"id": "101", "text": "look", "conversation_id": "101",
          "referenced_tweets": [{"type": "quoted", "id": "200"}]}
LINKER = {"id": "102", "text": "card", "conversation_id": "102",
          "entities": {"urls": [{"expanded_url": "https://x.com/i/article/1987654321098765432"}]}}
QUOTED_ARTICLE = {"id": "200", "article": {"title": "Quoted"}}  # no plain_text in includes


def route(path, q):
    if path == "/2/users/me":
        return 200, {"data": {"id": "42", "username": "me"}}, {}
    if path == "/2/users/42/bookmarks":
        if "post.fields" in q:
            return 400, {"title": "Invalid Request", "detail": "post.fields not allowed"}, {}
        return 200, {"data": [ARTICLE, QUOTER, LINKER],
                     "includes": {"tweets": [QUOTED_ARTICLE]}, "meta": {"result_count": 3}}, {}
    if path == "/2/tweets":
        ids = q["ids"].split(",")
        data = [{"id": "200", "article": {"title": "Quoted", "plain_text": "Full"}}]
        errors = [{"value": "1987654321098765432", "title": "Not Found Error", "detail": "no post"}]
        return 200, {"data": [d for d in data if d["id"] in ids],
                     "errors": [e for e in errors if e["value"] in ids]}, {}
    raise AssertionError(path)


def test_run_probe_answers_all_three_cases(tmp_path):
    lines = []
    report = probe.run_probe(XApi(FakeTransport(route)), tmp_path, log=lines.append)

    assert report["variants"]["tweet_fields"]["ok"]
    assert report["variants"]["post_fields"] == {
        "ok": False, "status": 400, "title": "Invalid Request",
        "detail": "post.fields not allowed",
        "body": {"title": "Invalid Request", "detail": "post.fields not allowed"}}
    assert report["traversal"]["total"] == 3
    call = report["bookmarks_call"]
    assert call["case_a_article"]["100"]["plain_text_len"] > 0
    assert call["case_a_article"]["100"]["zero_width"] == 1
    assert call["case_b1_quoted_article"]["101"]["200"]["plain_text_len"] == 0
    assert call["case_b2_article_link"]["102"]["link_ids"] == ["1987654321098765432"]
    assert report["lookups"]["200"]["found"] and report["lookups"]["200"]["plain_text_len"] == 4
    assert report["lookups"]["1987654321098765432"]["found"] is False
    saved = {p.name for p in tmp_path.iterdir()}
    assert {"me.json", "bookmarks-p01.json", "lookup-01.json", "report.json"} <= saved
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["cost"]["requests"]
    text = "\n".join(probe.summary_lines(report))
    assert "(a) article bookmarks: 1, with plain_text inline: 1" in text
    assert "ids=1987654321098765432" in text and "not found" in text


def test_cli_whoami_and_usage(capsys):
    import argparse

    handler = cli.make_handler(api_factory=lambda cfg: XApi(FakeTransport(route)))
    assert handler(argparse.Namespace(xbm_cmd=None)) == 2
    assert handler(argparse.Namespace(xbm_cmd="whoami", backend=None, xurl_app=None)) == 0
    assert "@me id 42" in capsys.readouterr().out
