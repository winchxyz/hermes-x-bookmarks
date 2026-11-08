"""Transports never leak the token; the X client pages, meters cost and maps errors."""
from __future__ import annotations

import datetime as dt

import pytest
from conftest import MARKER_TOKEN, FakeTransport

from hermes_x_bookmarks import auth
from hermes_x_bookmarks.auth import HttpResult, XurlTransport
from hermes_x_bookmarks.xapi import CostMeter, RateLimited, XApi, XApiError


def _page(ids, next_token=None, includes=None):
    body = {"data": [{"id": i, "text": f"post {i}"} for i in ids],
            "meta": {"result_count": len(ids)}}
    if next_token:
        body["meta"]["next_token"] = next_token
    if includes:
        body["includes"] = includes
    return body


def test_bookmark_pages_follow_next_token_and_use_page_size_90():
    pages = {None: _page(["3", "2"], "t1"), "t1": _page(["1"])}

    def route(path, q):
        assert path == "/2/users/42/bookmarks"
        return 200, pages[q.get("pagination_token")], {}

    t = FakeTransport(route)
    api = XApi(t)
    got = [p["data"][0]["id"] for p in api.bookmark_pages("42")]
    assert got == ["3", "1"]
    assert all(q["max_results"] == "90" for _, q in t.calls)
    assert "note_tweet" in t.calls[0][1]["tweet.fields"]
    assert "article" in t.calls[0][1]["tweet.fields"].split(",")


def test_max_pages_stops_early():
    t = FakeTransport(lambda p, q: (200, _page(["1"], "again"), {}))
    assert len(list(XApi(t).bookmark_pages("42", max_pages=3))) == 3


def test_rate_limit_and_errors():
    t = FakeTransport(lambda p, q: (429, {"title": "Too Many Requests"},
                                    {"x-rate-limit-reset": "1800000000"}))
    with pytest.raises(RateLimited) as exc:
        XApi(t).me()
    assert exc.value.reset_at == 1800000000

    t = FakeTransport(lambda p, q: (403, {"title": "Forbidden", "detail": "client-not-enrolled"},
                                    {}))
    with pytest.raises(XApiError, match="client-not-enrolled"):
        XApi(t).me()


def test_tweets_lookup_batches_by_100_and_dedupes():
    t = FakeTransport(lambda p, q: (200, _page(q["ids"].split(",")), {}))
    ids = [str(i) for i in range(150)] + ["1", "2"]
    batches = list(XApi(t).tweets(ids))
    assert [len(b["data"]) for b in batches] == [100, 50]


def test_cost_meter_owned_vs_standard_and_expansion_date():
    payload = _page(["1", "2"], includes={"users": [{}], "media": [{}, {}], "tweets": [{}]})
    before = CostMeter(today=dt.date(2026, 11, 8))
    before.add(payload, owned=True)
    assert before.usd == pytest.approx(0.002)
    after = CostMeter(today=dt.date(2026, 11, 22))
    after.add(payload, owned=True)
    assert after.usd == pytest.approx(0.006)
    std = CostMeter(today=dt.date(2026, 11, 22))
    std.add(payload, owned=False)
    assert std.usd == pytest.approx(2 * 0.005 + 0.005 + 0.010 + 2 * 0.005)


def test_xurl_transport_refetches_once_on_401_and_never_exposes_token(monkeypatch):
    issued = []

    def source(app):
        issued.append(app)
        return MARKER_TOKEN

    sent = []

    def fake_send(self, url, token):
        sent.append(token)
        return HttpResult(401 if len(sent) == 1 else 200, {}, b"{}")

    monkeypatch.setattr(XurlTransport, "_send", fake_send)
    t = XurlTransport(app="mine", token_source=source)
    assert t.get("https://api.x.com/2/users/me").status == 200
    assert issued == ["mine", "mine"]
    assert MARKER_TOKEN not in repr(t)


def test_xurl_missing_binary_is_a_clean_error(monkeypatch):
    monkeypatch.setattr(auth.shutil, "which", lambda name: None)
    with pytest.raises(auth.AuthUnavailable, match="xurl"):
        auth._run_xurl_token("")


def test_hermes_transport_outside_hermes_says_how_to_sign_in():
    with pytest.raises(auth.AuthUnavailable, match="hermes auth add hermes-x-bookmarks:x"):
        auth.HermesTransport().get("https://api.x.com/2/users/me")


KEYS = {"XBM_X_API_KEY": "ck", "XBM_X_API_SECRET": "cs", "XBM_X_ACCESS_TOKEN": "tk",
        "XBM_X_ACCESS_TOKEN_SECRET": "ts"}


def test_make_transport_picks_backend():
    assert auth.make_transport({}, environ={}).name == "hermes"
    assert auth.make_transport({}, environ=KEYS).name == "keys"
    assert auth.make_transport({"auth_backend": "hermes"}, environ=KEYS).name == "hermes"
    assert auth.make_transport({"auth_backend": "xurl", "xurl_app": "a"}).name == "xurl"


def test_keys_transport_names_missing_keys_never_values():
    partial = {**KEYS, "XBM_X_ACCESS_TOKEN_SECRET": ""}
    with pytest.raises(auth.AuthUnavailable) as exc:
        auth.KeysTransport(environ=partial).get("https://api.x.com/2/users/me")
    assert "XBM_X_ACCESS_TOKEN_SECRET" in str(exc.value)
    assert "ck" not in str(exc.value).replace("XBM", "")


def test_keys_transport_signs_with_oauth1(monkeypatch):
    import httpx

    seen = {}

    def fake_get(url, headers, timeout, follow_redirects):
        seen["auth"] = headers["Authorization"]
        return httpx.Response(200, json={"data": {"id": "1"}})

    monkeypatch.setattr(httpx, "get", fake_get)
    res = auth.KeysTransport(environ=KEYS).get("https://api.x.com/2/users/me?user.fields=id")
    assert res.status == 200
    assert seen["auth"].startswith("OAuth ")
    assert 'oauth_consumer_key="ck"' in seen["auth"] and 'oauth_token="tk"' in seen["auth"]
    assert "cs" not in seen["auth"].split("oauth_signature=")[0].replace("oauth_consumer", "")
