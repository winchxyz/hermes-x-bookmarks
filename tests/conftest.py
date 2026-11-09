"""Shared fixtures: fake Hermes ctx and a scripted X transport. No network."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
for _p in (ROOT, ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from hermes_x_bookmarks.auth import HttpResult  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_user_folders(tmp_path_factory, monkeypatch):
    """No test may write to the real Desktop or read the real Obsidian config."""
    from hermes_x_bookmarks import export_local, obsidian

    safe = tmp_path_factory.mktemp("user-folders")
    monkeypatch.setattr(export_local, "desktop_dir", lambda: safe / "Desktop")
    monkeypatch.setattr(obsidian, "obsidian_config_path", lambda platform=None: safe / "none.json")


MARKER_TOKEN = "xbm-MARKER-access-token-DO-NOT-LEAK"


class FakeCtx:
    """Records register_* calls like Hermes' PluginContext."""

    def __init__(self, config: dict | None = None) -> None:
        self.tools: dict[str, dict] = {}
        self.hooks: list[tuple[str, object]] = []
        self.commands: dict[str, dict] = {}
        self.cli: dict[str, dict] = {}
        self.skills: list[dict] = []
        self.config = dict(config or {})
        self.aux_tasks: dict[str, dict] = {}
        self.llm = None

    def register_tool(self, name, toolset, schema, handler, check_fn=None, requires_env=None,
                      is_async=False, description="", emoji="", override=False):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler}

    def register_hook(self, hook_name, callback, *, hold_stream=False):
        self.hooks.append((hook_name, callback))

    def register_command(self, name, handler, description="", args_hint="", argument_mode=None):
        self.commands[name] = {"handler": handler, "description": description}

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
        self.cli[name] = {"setup": setup_fn, "handler": handler_fn}

    def register_skill(self, name, path, description="", frontmatter=None):
        self.skills.append({"name": name, "path": Path(path), "description": description})

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def set_config(self, key, value):
        self.config[key] = value

    def register_auxiliary_task(self, key, *, display_name, description, defaults=None,
                                inherit_from=None):
        self.aux_tasks[key] = {"display_name": display_name, "inherit_from": inherit_from}


class FakeUsage:
    def __init__(self, i=100, o=50, cost=0.001):
        self.input_tokens, self.output_tokens, self.cost_usd = i, o, cost


class FakeResult:
    def __init__(self, parsed, model="fake-model"):
        self.parsed, self.model, self.usage = parsed, model, FakeUsage()
        self.text = json.dumps(parsed) if parsed is not None else "not json"


class FakeLlm:
    """``ctx.llm`` stand-in: ``answer(kwargs, texts) -> parsed`` (or raises)."""

    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        texts = [b["text"] for b in kwargs["input"]]
        return FakeResult(self.answer(kwargs, texts))


class FakeTransport:
    """Answers GETs from a routing function ``route(path, query) -> (status, json, headers)``."""

    name = "fake"

    def __init__(self, route) -> None:
        self.route = route
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str) -> HttpResult:
        parsed = urlparse(url)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.calls.append((parsed.path, query))
        status, body, headers = self.route(parsed.path, query)
        return HttpResult(status, headers or {}, json.dumps(body).encode("utf-8"))


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def fake_ctx():
    return FakeCtx()
