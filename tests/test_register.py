"""Registration matches plugin.yaml; the oauth entry has the shape Hermes accepts."""
from __future__ import annotations

from pathlib import Path

import yaml
from conftest import FakeCtx

from hermes_x_bookmarks import register

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))


def test_register_matches_manifest():
    ctx = FakeCtx()
    register(ctx)
    assert set(ctx.tools) == set(MANIFEST["provides_tools"])
    assert [h for h, _ in ctx.hooks] == MANIFEST["provides_hooks"]
    assert "xbm" in ctx.cli


def test_oauth_entry_is_read_only_public_client():
    entry = next(e for e in MANIFEST["oauth"] if e["id"] == "x")
    assert entry["hosts"] == ["api.x.com"]
    assert set(entry["scopes"]) == {"tweet.read", "users.read", "bookmark.read", "offline.access"}
    assert "client_secret_env" not in entry  # Native App: PKCE, no secret on disk
    declared = {e["name"] for e in MANIFEST.get("optional_env") or []}
    assert entry["client_id_env"] in declared


def test_google_entry_only_touches_files_it_made():
    entry = next(e for e in MANIFEST["oauth"] if e["id"] == "google")
    assert entry["scopes"] == ["https://www.googleapis.com/auth/drive.file"]
    assert entry["hosts"] == ["docs.googleapis.com"]
    assert entry["authorize_params"]["access_type"] == "offline"
    declared = {e["name"] for e in MANIFEST.get("optional_env") or []}
    assert {entry["client_id_env"], entry["client_secret_env"]} <= declared


def test_plugin_code_never_names_the_token_url():
    # Hermes refreshes the grant; validate warns when plugin code names the token URL.
    for entry in MANIFEST["oauth"]:
        for path in (ROOT / "hermes_x_bookmarks").rglob("*.py"):
            assert entry["token_url"] not in path.read_text(encoding="utf-8"), path


def test_new_settings_are_in_the_manifest():
    from hermes_x_bookmarks.commands import CONFIG_KEYS

    assert set(CONFIG_KEYS) <= set(MANIFEST["config_schema"])
