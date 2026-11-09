"""Google Docs export: one Google Doc "X Bookmarks", grouped by category, rewritten in place.

Sign-in is Hermes' plugin OAuth (``oauth: id: google`` in plugin.yaml) with your own Google
Cloud "Desktop app" client and only the ``drive.file`` scope: the plugin can touch the files it
created and nothing else in your Drive. Run ``hermes auth add hermes-x-bookmarks:google`` once;
Hermes keeps and refreshes the token and attaches it to each request. This module never sees it.

Every export replaces the content of the same document (same link, same sharing). If you
delete the document, the next export makes a new one.
"""
from __future__ import annotations

import datetime as _dt
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .export_local import UNSORTED, card
from .store import Store

OAUTH_ID = "google"
DOCS = "https://docs.googleapis.com/v1/documents"
SIGN_IN = "Run `hermes auth add hermes-x-bookmarks:google` in your own terminal to sign in."
STYLE_BATCH = 500  # style requests per batchUpdate

Request = Callable[[str, str, Any], tuple[int, Any]]


class GoogleError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Google {status}: {message}")
        self.status = status


@dataclass
class GdocsResult:
    url: str = ""
    count: int = 0
    new_document: bool = False
    errors: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        if self.errors:
            return ["Google Docs export failed."] + [f"  {e}" for e in self.errors]
        made = "Created" if self.new_document else "Updated"
        return [f"Google Docs: {made} the document with {self.count} bookmarks.",
                f"  {self.url}"]


def hermes_request(method: str, url: str, body: Any) -> tuple[int, Any]:
    """One request with the user's Google sign-in attached by Hermes."""
    try:
        from hermes_cli.plugin_provider_requests import (
            ProviderNotSignedIn,
            credentialed_provider_request,
        )
    except ImportError:
        raise GoogleError(0, "Google export needs a running Hermes. " + SIGN_IN) from None
    try:
        resp = credentialed_provider_request(OAUTH_ID, method, url, json=body, timeout=60.0)
    except ProviderNotSignedIn:
        raise GoogleError(401, "not signed in. " + SIGN_IN) from None
    except Exception as exc:  # noqa: BLE001 - refresh failed, client id missing, ...
        code = getattr(exc, "code", "") or type(exc).__name__
        raise GoogleError(401, f"sign-in problem ({code}). " + SIGN_IN) from None
    try:
        data = json.loads(resp.body or b"null")
    except ValueError:
        data = None
    return resp.status, data


def _units(s: str) -> int:
    """Length in UTF-16 code units: the Docs API counts indexes that way."""
    return len(s.encode("utf-16-le")) // 2


class DocBuilder:
    """Plain text plus style ranges; indexes start at 1 (the body start)."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.pos = 1
        self.styles: list[dict[str, Any]] = []

    def _add(self, text: str) -> tuple[int, int]:
        start = self.pos
        self.parts.append(text)
        self.pos += _units(text)
        return start, self.pos

    def heading(self, text: str, style: str) -> None:
        start, _ = self._add(text)
        self.parts.append("\n")
        self.pos += 1
        self.styles.append({"updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": self.pos},
            "paragraphStyle": {"namedStyleType": style}, "fields": "namedStyleType"}})

    def text(self, text: str, *, link: str = "", bold: bool = False, italic: bool = False,
             gray: bool = False) -> None:
        if not text:
            return
        start, end = self._add(text)
        style: dict[str, Any] = {}
        fields = []
        if link:
            style["link"] = {"url": link}
            fields.append("link")
        if bold:
            style["bold"] = True
            fields.append("bold")
        if italic:
            style["italic"] = True
            fields.append("italic")
        if gray:
            style["foregroundColor"] = {"color": {"rgbColor": {"red": 0.42, "green": 0.42,
                                                               "blue": 0.42}}}
            fields.append("foregroundColor")
        if fields:
            self.styles.append({"updateTextStyle": {
                "range": {"startIndex": start, "endIndex": end}, "textStyle": style,
                "fields": ",".join(fields)}})

    def newline(self) -> None:
        self._add("\n")

    @property
    def body(self) -> str:
        return "".join(self.parts)


def build_doc(cards: list[dict[str, Any]], generated: str, owner: str = "") -> DocBuilder:
    doc = DocBuilder()
    doc.heading(f"X Bookmarks{f' of @{owner}' if owner else ''}", "TITLE")
    doc.text(f"{len(cards)} bookmarks, exported {generated} by hermes-x-bookmarks. "
             "Highest priority first in each category.", gray=True)
    doc.newline()
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in cards:
        groups[c["category"]].append(c)
    order = sorted(groups, key=lambda g: (g == UNSORTED, -len(groups[g]), g))
    for g in order:
        doc.heading(f"{g} ({len(groups[g])})", "HEADING_1")
        for c in sorted(groups[g], key=lambda c: (c["priority"] or 9)):
            head = c["title"] or c["summary"] or c["text"][:140] or "(media only)"
            badge = " · ".join(x for x in (f"P{c['priority']}" if c["priority"] else "",
                                           c["kind"]) if x)
            if badge:
                doc.text(f"[{badge}] ", bold=True)
            doc.text(" ".join(head.split()), link=c["url"])
            doc.text(f"  @{c['author']}, {c['date']}", gray=True)
            doc.newline()
            if c["title"] and c["summary"]:
                doc.text(c["summary"])
                doc.newline()
            if c["why"]:
                doc.text("Why saved: " + c["why"], italic=True, gray=True)
                doc.newline()
            if c["tags"]:
                doc.text(" ".join(f"#{t}" for t in c["tags"]), gray=True)
                doc.newline()
            doc.newline()
    return doc


def _call(request: Request, method: str, url: str, body: Any = None) -> Any:
    status, data = request(method, url, body)
    if status >= 400:
        msg = ""
        if isinstance(data, dict):
            msg = str((data.get("error") or {}).get("message") or "")
        raise GoogleError(status, msg[:300] or "request failed")
    return data


def _end_index(request: Request, doc_id: str) -> int | None:
    """End index of the document body, or None when the document is gone or not ours."""
    try:
        data = _call(request, "GET", f"{DOCS}/{doc_id}?fields=body.content.endIndex")
    except GoogleError as exc:
        if exc.status in (403, 404):
            return None
        raise
    content = ((data or {}).get("body") or {}).get("content") or []
    return max((int(e.get("endIndex") or 0) for e in content), default=1)


def export(store: Store, *, request: Request | None = None,
           now: _dt.datetime | None = None) -> GdocsResult:
    req = request or hermes_request
    res = GdocsResult()
    generated = (now or _dt.datetime.now()).strftime("%Y-%m-%d %H:%M")
    cards = [card(i, lab) for i, lab in store.labelled_items()]
    doc = build_doc(cards, generated, store.get_meta("x_username"))
    try:
        doc_id = store.get_meta("gdocs_document_id")
        end = _end_index(req, doc_id) if doc_id else None
        if end is None:
            created = _call(req, "POST", DOCS, {"title": "X Bookmarks"})
            doc_id = created["documentId"]
            store.set_meta("gdocs_document_id", doc_id)
            res.new_document = True
            end = 2
        first: list[dict[str, Any]] = []
        if end > 2:
            first.append({"deleteContentRange": {"range": {"startIndex": 1,
                                                           "endIndex": end - 1}}})
        first.append({"insertText": {"location": {"index": 1}, "text": doc.body}})
        whole = {"startIndex": 1, "endIndex": doc.pos}
        first.append({"updateParagraphStyle": {"range": whole, "paragraphStyle": {
            "namedStyleType": "NORMAL_TEXT"}, "fields": "namedStyleType"}})
        first.append({"updateTextStyle": {"range": whole, "textStyle": {},
                                          "fields": "bold,italic,link,foregroundColor"}})
        _call(req, "POST", f"{DOCS}/{doc_id}:batchUpdate", {"requests": first})
        for k in range(0, len(doc.styles), STYLE_BATCH):
            _call(req, "POST", f"{DOCS}/{doc_id}:batchUpdate",
                  {"requests": doc.styles[k:k + STYLE_BATCH]})
    except GoogleError as exc:
        hint = ""
        if exc.status == 403:
            hint = (" Enable the Google Docs API in your Google Cloud project "
                    "(APIs & Services → Library → Google Docs API).")
        res.errors.append(str(exc) + hint)
        return res
    except (KeyError, TypeError):
        res.errors.append("Google sent an answer the plugin did not expect.")
        return res
    res.url = f"https://docs.google.com/document/d/{doc_id}/edit"
    res.count = len(cards)
    return res
