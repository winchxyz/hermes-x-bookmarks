# Hermes platform research for the X bookmarks plugin

Researched 2026-11-07 against `NousResearch/hermes-agent` `main` (local sparse clone at
`b52b8b00`, 2026-11-07 07:52 UTC; live `main` was `cf7003f3`, 08:13 UTC, 670 commits after the
`v0.23.0` release). File references are `path:line` at that commit unless a tag is named. The
reference plugin is [winchxyz/hermes-ghost-call](https://github.com/winchxyz/hermes-ghost-call) (catalog PR #150554, still open, no
reviews, no checks reported).

Short names used below: `index.md` = `website/docs/developer-guide/plugins/index.md`,
`llm.md` = `website/docs/developer-guide/plugin-llm-access.md`, `cron.md` =
`website/docs/user-guide/features/cron.md`, `plugins.md` = `website/docs/user-guide/features/plugins.md`,
`ctx` = `hermes_cli/plugins_context.py` (`PluginContext`).

## How ghost-call uses the platform (baseline)

- `__init__.py` at the repo root re-exports `register` from the package (relative import with an
  absolute fallback for pytest).
- `hermes_ghost_call/__init__.py` `register(ctx)`: `ctx.register_tool(name, toolset="ghost", schema,
  handler, description)` for 7 tools, `ctx.register_hook("pre_tool_call", ...)`,
  `ctx.register_command("ghost", handler, description, args_hint)`,
  `ctx.register_cli_command(name="ghost", help, setup_fn, handler_fn, description)`, and
  `ctx.register_skill("ghost-call", skills/ghost-call/SKILL.md, description)` behind a `getattr`
  probe. No network and no heavy imports in `register()`.
- Slash command: one handler parses `raw_args` into subcommands (`start|status|speak|...`) and reads
  session keywords (`session_id`, `user_id`, `platform`) from `**kwargs` (`commands.py`).
- Hook: `pre_tool_call(tool_name="", args=None, **kwargs)` returns `{"action": "block", ...}` for one
  gated tool, fails closed (`hooks.py`). Unattended detection uses `ctx.current_cron_execution()` and
  `ctx.session_surface()` (`safety.py:119-125`).
- Messages: `ctx.post_message(text)` with `.edit()` for a live ticker (`watcher.py`).
- Storage: `from plugins.plugin_storage import plugin_data_dir` -> `<HERMES_HOME>/plugin-data/<name>/`
  SQLite, with `HERMES_HOME` fallback outside Hermes (`session.py:109-121`).
- Secrets: `from agent.secret_scope import get_secret`, fail closed on scope errors, `os.environ` only
  when the module is absent (`secrets.py`).
- Tests: `tests/conftest.py` has a `FakeCtx` recording `register_*`, `post_message`, `get_config`,
  `current_cron_execution`, `session_surface`; no network.
- CI (`.github/workflows/ci.yml`): ruff + pytest on 3.11/3.12; a `hermes-plugin-checks` job that
  checks out hermes-agent at `HERMES_AGENT_SHA`, `uv sync --frozen --python 3.14`, then
  `hermes plugins validate . --install-deps` and `hermes plugins doctor . --ci` with `HERMES_HOME`
  outside the plugin dir.

The new plugin needs more of the `ctx` surface than ghost-call did: `ctx.llm`, `ctx.state` /
`plugin_db`, `oauth:` + `credentialed_provider_request`, `ctx.call_mcp`,
`ctx.register_automation_blueprint`, `ctx.dispatch_tool`, `ctx.ask_choice`. The test `FakeCtx`
must grow accordingly.

## 1. Scheduling

**There is no plugin cron/timer API** (no `ctx.register_cron`, no `ctx.schedule`). `PluginContext`
methods are listed at `ctx:36-883`; scheduling-related ones are:

| Surface | What it does | Ref |
|---|---|---|
| `ctx.register_automation_blueprint(key, title, description, schedule_template, prompt_template, category, slots, deliver_default, skills, tags)` | Adds a fill-in-the-blanks automation to `/blueprint`, the dashboard Blueprints tab and the Desktop Cron page. Scheduling it creates an **ordinary cron job**. Key is namespaced `<plugin>:<key>`. Slots: `time`, `enum`, `weekdays`, `text`; a slot named `deliver` gets the profile's real delivery targets. Validated at registration. Jobs outlive the plugin. No capability needed, works under `plugins.isolation: host`. | `index.md:2067-2098`, `hermes_cli/plugins_content.py:69`, `cron/blueprint_plugins.py` |
| `ctx.dispatch_tool("cronjob_manage", {...})` | Public way to call any registered tool from a slash command or hook. **Correction (2026-11-08):** it calls `registry.dispatch` directly (`tools/registry.py:972`, main 856e7580 and v0.23.0), skipping the availability check, all `pre_tool_call` hooks and middleware; only guards inside the tool run. Confirm side effects in our own code. The cron tool is registered as `cronjob_manage` (`tools/cronjob_tools.py:1264`); docs call it `cronjob(action=...)`. | `index.md:940,1898-1935`, `ctx:483` |
| `ctx.current_cron_execution()` | Inside a cron run: frozen `CronExecution(job_id, job_name, execution_id, source, scheduled_instant, started_at, profile)`, else `None`. Unforgeable by the model. Use it to tell a scheduled run from a chat turn. | `index.md:2043-2065`, `ctx:218` |
| `ctx.spawn_task(coro)` | Supervised asyncio task, cancelled on unload; **needs a running loop** (not usable from sync `register()`). | `ctx:232` |

Precedent in the catalog: `author-feed` creates its own cron job from `hermes author-feed schedule`
by importing the private `cron.jobs.create_job` (its entry discloses "relies on private Hermes
parts"). `cron.jobs` is **not** in the public import list
(`website/docs/developer-guide/plugins/public-api.md`), so validate would warn (rule 9). Do not copy
that.

**Cron job model** (`cron.md`): jobs run in a fresh agent session (`cron.md:1313-1332`), on the
per-job pin, then `cron.model`, then the main model (`cron.md:27-31`). Per-job
`enabled_toolsets=[...]` limits tools (cost control). Options that matter for us:
- `deliver`: `origin` (chat where created), `local` (`~/.hermes/cron/output/`), `telegram` (home
  channel via `TELEGRAM_HOME_CHANNEL`), `telegram:<chat>[:thread]`, `discord`, `slack`, `all`,
  comma lists, `bot-chat` (`cron.md:645-676`). "The agent's final response is automatically
  delivered" (`cron.md:678`). Output is secret-redacted (`cron.md:680-687`).
- `[SILENT]` anywhere in the final response suppresses delivery (`cron.md:898-909`) -> "nothing new
  this week" ticks stay quiet. `[CRON_FAILURE]` on line 1 marks a failed run (`cron.md:911`).
- `attach_to_session: true` / `cron.mirror_delivery` makes a delivery **continuable**: the user can
  reply to the digest in-thread with full context ("turn #3 into a task") (`cron.md:791-839`).
- `no_agent=True` script jobs run a file from `$HERMES_HOME/scripts/` only, with a sanitized env
  (no Hermes secrets), stdout delivered verbatim (`cron.md:979-1011`). A plugin cannot hand its own
  module to this path without writing into `scripts/` (outside its data dir), so it is a poor fit.
- `script=` pre-check can emit `{"wakeAgent": false}` to skip the agent turn (`cron.md:1336-1352`);
  same `scripts/` restriction.
- Cron sessions cannot create cron jobs (`cron.md:42-44`).

**Proactive messages outside a cron job:**
- `ctx.post_message(text)` posts into the session bound to the current call only; from a timer,
  thread, cron or no-gateway process it is refused with `ok=False` (`hermes_cli/plugin_messages.py:1-8`,
  `ctx:414`).
- `ctx.inject_message(content, role, session_key=|origin=)` queues **user input** (it triggers an
  agent turn; it is not a plain send). Needs operator opt-in
  `plugins.entries.<id>.allow_gateway_injection: true` (`plugins.md:1131-1137`,
  `hermes_cli/plugins_injection.py:36-40`); an `origin` chat needs a human message already admitted
  there; never another profile (`plugins.md:1058-1146`).
- `send_message` is deliberately **not** an agent tool and not a public import
  (`tools/send_message_tool.py:28`); cron delivery and `hermes send` use it.
- Telegram/Discord inline buttons are possible only through `ctx.register_platform_handler`
  (see section 6), not on cron deliveries.

**Answer:** the plugin should not run its own scheduler. Register blueprints
(`x-bookmarks:sync`, `x-bookmarks:weekly-digest`) and offer `/xbm schedule` that calls
`ctx.dispatch_tool("cronjob_manage", {"action": "create", ...})` with `enabled_toolsets` set to the
plugin's toolset, the plugin's bundled skill attached (`skills: ["x-bookmarks:digest"]`) and the
user's chosen `deliver`. The job prompt tells the agent to call `xbm_sync` / `xbm_digest` and reply
with the returned text verbatim, or `[SILENT]` when there is nothing new. Delivery to Telegram,
Discord, CLI (`local`) etc. is then Hermes's job.

## 2. LLM access (no extra API key)

**Yes: `ctx.llm`** (`agent.plugin_llm.PluginLlm`, `ctx:183-191`, docs `llm.md`). It runs on the
user's active provider/model with host-owned credentials (OAuth, pools, fallback chain, vision
routing). Methods: `complete(messages, ...)`, `complete_structured(instructions, input,
json_schema, schema_name, json_mode, system_prompt, ...)`, async `acomplete` /
`acomplete_structured` (`agent/plugin_llm.py:486-535`, `llm.md:209-292`). Results carry `text`,
`provider`, `model`, `usage` (tokens, `cost_usd`), `audit`; structured results add `parsed` and
`content_type` (`llm.md:452-474`).

Plugin-owned model slot: `ctx.register_auxiliary_task("classify", display_name, description,
defaults=, inherit_from=)` (`ctx:661-682`), then `ctx.llm.complete_structured(..., task="classify")`.
The slot appears in `hermes model` -> auxiliary picker, dashboard Models page and Desktop Settings
-> Models -> Auxiliary; `inherit_from="compression"` (or another built-in slot) makes it follow that
slot until the user pins a cheap model on ours (`llm.md:294-331,415-450`).

Limits and rules:
- Single bounded call: **no streaming, no tool loops, no conversation state** (`llm.md:89-91`).
- Trust gate, fail closed: `provider=`, `model=`, `agent_id=`, `profile=` raise
  `PluginLlmTrustError` unless the operator sets `plugins.entries.<id>.llm.allow_*_override`;
  `task=` may only name the plugin's own registered task (`llm.md:476-561`). Declaring
  `capabilities: [llm.model_override]` adds a consent prompt (`index.md:386-417`).
- `complete_structured` raises `ValueError` on empty input or (with `jsonschema` installed) schema
  mismatch; `parsed` is `None` when the reply is not JSON (`llm.md:276-279,410-413,596-600`).
- Every call costs the user's provider; one INFO audit line per call with `purpose`
  (`llm.md:51-53,587-603`). Batch bookmarks (for example 20-40 per call) and cache results.
- `ctx.side_question` (ask the session's own agent after a turn) needs `capabilities:
  [llm.side_question]`, gets `None` under cron, one attempt per turn, 60 s token — not useful for
  batch classification (`llm.md:605-692`).
- Never call it from `register()` (Doctor blocks sockets, section 7).

Built-in precedent: `cron/scripts/classify_items.py` scores a JSON batch with one call to the
auxiliary `monitor` model and prints only items above a threshold. Same shape as our classifier.

Ghost-call called OpenAI with its own key (`OPENAI_API_KEY`); this plugin does not need that.

## 3. Skills

Three routes:

1. **Plugin-bundled skill (read-only)**: `ctx.register_skill(name, path, description="",
   frontmatter=None)` (`hermes_cli/plugins_content.py:32-67`). Resolves as `<plugin>:<name>` via
   `skill_view`; not copied into `~/.hermes/skills/`; cannot be edited with `skill_manage`
   (`index.md:1181-1222`). Note a doc/code mismatch: `index.md:1216` says plugin skills are not in
   `<available_skills>`, while the code docstring (`plugins_content.py:36-38`) says they are listed by
   `skills_list` and in the system prompt index while the plugin is enabled. `path` only has to exist,
   so it could point into the plugin data dir; tools/prompt changes apply from the next session.
   Use this for our own "how to use x-bookmarks" skill and for cron jobs' `skills:` list.
2. **User skill via `skill_manage`** (the right way to "turn a bookmark into a Hermes skill"):
   `ctx.dispatch_tool("skill_manage", {"operations": [{"action": "create", "name": "...",
   "category": "...", "content": "<full SKILL.md>"}]})`. Schema at
   `tools/skill_manager_tool.py:877-917` (actions `create`, `patch`, `write_file`, `remove_file`,
   `delete`, ...). New skills land in `~/.hermes/skills/[category/]<name>/SKILL.md` or
   `skills.create_dir` (`skill_manager_tool.py:1-8,212-220`). Limits: name 64 chars, description 1024,
   SKILL.md 100,000 chars, supporting files 1 MiB (`skill_manager_tool.py:108-111`). Agent-created
   skill scanning is opt-in (`skills.guard_agent_created`, `skill_manager_tool.py:41-46`). Because it
   is a direct registry dispatch, hooks and middleware do **not** run (see the correction in
   section 1); confirm with the user in our own code first. Alternatively our tool returns a drafted SKILL.md and the
   agent itself calls `skill_manage`.
3. **Writing files into `HERMES_HOME/skills` directly**: works (legacy `shutil.copy2` pattern,
   `index.md:1220-1222`) but is a write outside the plugin's data dir (rule 13 disclosure) and skips
   the guards. Avoid.

Reading the catalog (dedupe before creating): public helpers `tools.skills_tool.find_all_skills`,
`locate_skill`, `skill_lookup_path_error`, `skill_search_dirs` (`index.md:1224-1256`).

**SKILL.md format** (`website/docs/developer-guide/creating-skills.md:44-99`): YAML frontmatter with
`name`, `description` (shown in search; keep the first sentence short), `version`, `author`,
`license`, optional `platforms: [macos, linux, windows]`, `metadata.hermes.{tags, related_skills,
requires_toolsets, requires_tools, fallback_for_toolsets, fallback_for_tools, config, blueprint}`,
`required_environment_variables`; body sections "When to Use", "Quick Reference", "Procedure",
"Pitfalls", "Verification". `metadata.hermes.blueprint: {schedule, deliver, prompt, no_agent}`
marks a skill as a runnable automation (`creating-skills.md:344-378`). Ghost-call's
`skills/ghost-call/SKILL.md` used only `name` + `description`.

## 4. Secrets and OAuth tokens

- **API keys / static secrets**: declare in `requires_env` (gates loading: plugin disabled if missing,
  prompted at install) or `optional_env`; rich form `{name, description, url, secret: true}`
  (`index.md:377-389,1307-1340`). Read with `agent.secret_scope.get_secret(NAME)` (catalog rule 11).
  `config_schema` `type: secret` with `env: NAME` gives a masked field in Desktop Settings ->
  Plugins; the value goes to `.env`, never `config.yaml` (`index.md:996-1032`).
- **Refreshable OAuth tokens: Hermes owns them.** Declare `oauth:` in `plugin.yaml`
  (`index.md:515-605`, `hermes_cli/plugin_oauth.py`): `id`, `authorize_url`, `token_url`, `scopes`,
  `client_id_env`, optional `client_secret_env`, `hosts`, optional `authorize_params`. The user runs
  `hermes auth add <plugin>:<id>` in a terminal (loopback PKCE on `127.0.0.1`, SSH tunnel hint;
  refuses to run from gateway/cron/agent). The grant is stored in the profile's `auth.json`
  section `plugin_oauth`, refreshed under the auth-store lock when < 2 min remain, and **rotated
  refresh tokens are saved** (`plugin_oauth.py:390-408`, `_write_grant(key, {**row, **fields})`).
  Calls go through `hermes_cli.plugin_provider_requests.credentialed_provider_request(id, method,
  url, *, json=None, headers=None, timeout=30.0)` (`plugin_provider_requests.py:134`): bearer only
  to the declared `hosts` (exact, https:443), no redirects followed, errors without token material.
  Errors: `ProviderNotSignedIn`, `AuthError` codes `oauth_client_id_missing`,
  `oauth_client_secret_missing`, `invalid_client`, `unauthorized_client`, `invalid_scope`,
  `oauth_refresh_failed` (`index.md:588-596`). The grant is pinned to a fingerprint of the entry:
  changing token URL, hosts, scopes or client vars forces a new sign-in (`plugin_oauth.py:44-52`).
  `hermes plugins remove` drops the grants.
- Constraints of that helper: the caller must be code inside an **installed** plugin dir on the call
  stack (`run_in_executor(helper)` directly is refused; wrap it) (`index.md:483-488`); only JSON
  bodies (no form/multipart); sync httpx; client vars must be declared in `requires_env` or
  `optional_env` (`plugin_oauth.py:194-205`); the oauth `id` may not be a core provider id (today only
  `openai-codex`); validate warns if plugin code contains the token URL (`plugin_oauth.py:218-233`).
- **X blocker to check first:** the plugin `oauth:` entry has **no `redirect_port`**; the login binds
  an OS-assigned port, `redirect_uri = http://127.0.0.1:<random>/callback`
  (`hermes_cli/auth_oauth_pkce_plugin.py:48,163-175`; `_pkce_config` passes no port,
  `plugin_oauth.py:348`). X documents "exact match validation for your callback URL". Open issue
  **#149642** "Plugin oauth: entries: expose redirect_port for IdPs that require exact-match redirect
  URIs" (open, updated 2026-11-06). Also the token POST sends `client_secret` in the form body
  (`plugin_oauth.py:319-330`); X confidential clients authenticate with an `Authorization` header, so
  use an X **public (Native App) client** with PKCE and no secret. Scopes for bookmarks:
  `tweet.read users.read bookmark.read offline.access` (+ `bookmark.write` only if we unbookmark).
  Google Desktop clients accept any loopback port, so Google works today.
- **Where the plugin's own runtime state goes**: `plugins.plugin_storage.plugin_data_dir(name)` /
  `plugin_db(name)` (SQLite WAL) under `<HERMES_HOME>/plugin-data/<name>/` (`index.md:1159-1179`) or
  `ctx.state.get/set` (profile-scoped, atomic, 10 MiB cap, `index.md:978-994`). "Secrets don't belong
  here." So: bookmarks DB and cursors in plugin data; **never** tokens.
- **Catalog rule 11** (`plugin-catalog/README.md:91-107`): secrets only via Hermes routes; never read
  `.env`, `auth.json`, another tool's login (vendor CLI token file, browser profile, keychain); never
  refresh, rotate or write OAuth tokens; never present as another vendor's client; if no route exists,
  ask in a Hermes issue. Rule 12: anything waiting for a person (OAuth browser flow) must fail cleanly
  under cron/gateway.
- **Other built-in OAuth routes**: MCP servers have their own OAuth manager (`hermes mcp login
  <server>`), used e.g. by the optional Notion MCP (section 5). The xurl skill keeps its tokens in
  `~/.xurl`; reading that file is forbidden, but running the `xurl` CLI is what the catalog-listed
  `x-dashboard` does (`plugin-catalog/x-dashboard.yaml`, disclosed). `xai-oauth` is the xAI (Grok)
  sign-in, not the X API.

## 5. Notion, Google, xurl, x_search: reuse, do not duplicate

- **Notion**: no bundled Notion skill or tool. There is a Nous-approved optional **Notion MCP**
  entry: vendor-hosted `https://mcp.notion.com/mcp`, OAuth 2.1 + DCR handled by Hermes's MCP client
  (`optional-mcps/notion/manifest.yaml`). A plugin can call it with `ctx.call_mcp(server, tool,
  arguments, timeout=30)` (`ctx:309-339`): default-deny, needs
  `plugins.entries.<id>.mcp_allowlist: ["notion"]` in `config.yaml` (`plugins.md:1159-1197`); timeout
  1-600 s; results over 64 KB truncated. That gives Notion export with no Notion token in the
  plugin. Fallback: a Notion internal-integration token as an `optional_env` secret
  (`NOTION_API_KEY`) through `get_secret`. Notion public OAuth via `oauth:` is risky (Notion's token
  endpoint expects Basic auth; Hermes posts the secret in the form).
- **Google**: the bundled `skills/productivity/google-workspace` skill (Gmail, Calendar, Drive, Docs,
  Sheets via `gws` CLI or a Python client) stores `google_token.json` / `google_client_secret.json`
  under `HERMES_HOME` (`SKILL.md` frontmatter `required_credential_files`). The plugin must not read
  those files (rule 11). The supported plugin path is our own `oauth: - id: google` entry with
  `documents` + `drive.file` scopes, exactly the example in `index.md:515-566`. We should not
  re-implement Gmail/Calendar; only "create/append a Doc" for exports.
- **xurl skill** (`skills/social-media/xurl/SKILL.md`, v1.1.3, `platforms: [linux, macos]`): wraps
  the official `xurl` CLI; `xurl bookmarks -n N`, `xurl bookmark ID`, `xurl unbookmark ID`
  (lines 145-146, 226-229). Secret rules: never read `~/.xurl`, never pass inline secrets, only
  `xurl auth status` to check. User registers the app with redirect `http://localhost:8080/callback`.
  Relation: our plugin adds what xurl lacks (storage, dedupe, classification, exports, digest,
  conversions). Do not duplicate posting/DM/likes. An optional "xurl backend" (subprocess `xurl
  bookmarks`) is a workable fallback while #149642 is open, with disclosure; not on Windows per the
  skill's `platforms`.
- **x_search** (`website/docs/user-guide/features/x-search.md`, `tools/x_search_tool.py`): read-only
  public X discovery through xAI Responses (Grok); needs `XAI_API_KEY` or `xai-oauth`. Cannot read a
  user's private bookmarks ("Bookmarks are private", X docs). Our digest skill can suggest
  `x_search` for "what else is being said about this bookmark" but must not depend on it.
- Catalog: no existing bookmarks plugin (searched `plugin-catalog/` and open PRs). `x-dashboard`
  (analytics) is the nearest X plugin. Rules 15/16 (no forks of bundled/listed plugins) are not a
  problem.

## 6. UI surfaces

- **Slash command with subcommands**: `ctx.register_command(name, handler, description, args_hint,
  argument_mode=None|"options"|"text"|"mixed")` (`ctx:456-480`, `index.md:1786-1865`). Handler gets
  `raw_args` plus declared keywords `session_id`, `session_key`, `platform`, `source`
  (`SessionSource` with `user_id`, `chat_id`, ...). Runs in the gateway process: return text, use
  `agent.runtime_cwd.resolve_agent_cwd()` and `gateway.session_context.get_session_env(...)`, not
  `os.getcwd()` / `os.environ`. Conflicts with built-ins are dropped silently. Appears in the Telegram
  bot menu.
- **Choice buttons**: `ctx.ask_choice(question, choices)` from a **sync** slash handler: Telegram,
  Discord, Slack get one button per choice; other platforms a numbered list; CLI/TUI/Desktop the
  clarify picker; returns `None` from hooks, cron, async handlers (`index.md:1867-1896`, `ctx:425`).
  Good for `/xbm export` -> pick Notion / Google Doc / local file.
- **Custom inline buttons in our own messages**: `ctx.register_platform_handler("telegram", factory)`
  (PTB `Application`; scope `CallbackQueryHandler(pattern=r"^xbm:")`), Discord listeners, Slack via
  `ctx.register_slack_action_handler` (`index.md:2100-2209`). Requires `plugins.isolation:
  in_process` (`plugins.md:925-937`). Cron deliveries are plain text, so buttons on the digest are not
  free; use numbered items plus continuable delivery or `/xbm task 3`.
- **Approval for side effects**: a `pre_tool_call` hook returning `{"action": "approve", "message",
  "rule_key"}` escalates to the human-approval gate; denial, timeout or gate error fails closed;
  `block` > `approve` (`website/docs/user-guide/features/hooks.md:570-578`). A hook that raises or
  exceeds `plugins.hook_callback_timeout` **blocks the tool** (`hooks.md:596`), and the hook fires for
  every tool, so return `None` fast for anything not ours. Under cron an `approve` will fail closed:
  scheduled exports need a separate user setting plus `ctx.current_cron_execution()` check.
  `ctx.register_approval_transport` exists for custom approval UIs (`ctx:244`), not needed.
- **Settings form**: every `config_schema` key renders in Desktop Settings -> Plugins (types `str`
  with `choices`, `int`, `float`, `bool`, `list`, `dict`, `secret`; `label`, `description`,
  `default`, `required`) (`index.md:996-1061`). Saves broadcast `plugin.<id>.settings.changed`.
- **Web dashboard tab**: `dashboard/manifest.json` + pre-built `dashboard/dist/index.js` (IIFE) +
  optional `dashboard/plugin_api.py` exporting a FastAPI `router` mounted at `/api/plugins/<name>/`
  behind dashboard auth; do not block the event loop
  (`website/docs/user-guide/features/extending-the-dashboard.md:427-787`).
- **Desktop app page**: unified package `desktop/plugin.js` (plain ESM, no build) inside the plugin
  folder; `ROUTES_AREA` + `SIDEBAR_NAV_AREA` for a page, panes, palette commands, status bar,
  `TRANSCRIPT_DIRECTIVE_AREA` (the model writes `::xbm{id="..."}` and Desktop renders our card
  inline), `ctx.rest` to the same `plugin_api.py` (`website/docs/developer-guide/desktop-plugin-sdk.md:35-90,297-321,1100-1125,2130-2175`).
  Catalog rule 8 restricts it to `@hermes/plugin-sdk` / `react` imports, no DOM patching.
- **Plugin RPC / session events** (new since ghost-call's pin): `ctx.register_rpc(name, handler)`,
  `ctx.emit_to_session(session_id, event, payload)` for a frontend attached to the gateway
  (`index.md:1959-2029`, commits `aa3934771`, `be3d288fa`).

## 7. Manifest v2 and validation

Known manifest fields (`hermes_cli/plugins_manifest.py:32-39`): `name, version, description,
author, requires_env, optional_env, provides_tools, provides_hooks, kind, hooks, label, platforms,
external_dependencies, pip_dependencies, provides_browser_providers, provides_web_providers,
manifest_version, api_version, requires_plugins, python_dependencies, config_schema, license,
homepage, tags, capabilities, emits, listens, hermes, depends, requires_hermes, python_runtime,
provides_locales, requires_auth, oauth, config_keys`. `SUPPORTED_MANIFEST_VERSION = 2`. Unknown
fields warn under v2, never fail. There is **no `provides_middleware` or `provides_commands` manifest
field**; middleware is compared against the catalog entry's `capabilities.provides_middleware`.

**`hermes plugins validate <dir> [--install-deps]`** (`hermes_cli/plugin_validate.py`, `validate_plugin_dir`
at line 502) adds named checks: `manifest` parses; `manifest fields` (name, version, description);
`requires_hermes` parses; `config schema` types; `requires_env` UPPER_SNAKE; `oauth` (shape, https,
declared client vars, no core id; warnings for foreign hosts and token URL in code, lines 188-233);
`capability probe` (imports the plugin and runs `register(ctx)` in a scratch subprocess against a
stub whose methods mirror the real `PluginContext`, 30 s timeout); `declared tools|hooks|middleware`
(an **undeclared** registration fails; a declared but unregistered one warns, lines 407-475);
`built-in tool collisions`; `trusted inbound`; loadability (`plugin.yaml` needs `__init__.py`,
`desktop/plugin.js` or `plugin.json`); `python dependencies` (PEP 508, resolves under Hermes core
constraints; `pyproject.toml` wins over `python_dependencies`, lines 596-617); `security scan`
(`dangerous` fails, `caution` warns, line 621); `desktop surface`; `no core override`; private Hermes
imports warn (`plugin_validate_private_imports.py`, list in `public-api.md`); language packs;
plugin-host isolation audit (informational).

**`hermes plugins doctor <dir> --ci`** (`hermes_cli/plugin_dev.py`): stages the plugin under a temp
`HERMES_HOME`, runs the real discovery/import/`register()`, **blocks `socket.create_connection`,
`socket.connect`, `connect_ex`** while registering (lines 27-29, 94-96; "network access is disabled
while Plugin Doctor runs"), errors on unknown hook names, non-list `provides_*`, callbacks without
`**kwargs` (lines 460-480); warns on declared-vs-registered drift, bad `api_version`,
`requires_plugins`, unknown `config_schema` types. `--ci` exits non-zero on errors. Doctor needs
`HERMES_HOME` outside the plugin dir (ghost-call CI comment).

**Catalog entry `capabilities:`** (`plugin-catalog/README.md:178-209`): `provides_tools`,
`provides_hooks`, `provides_middleware`, `requires_env`, plus top-level `platforms` (empty = all),
`category` (`desktop|memory|platform|web|tools|voice|automation|models|general`), `requires_hermes`,
`version` (quoted), `image` (2:1, GitHub host, pinned), up to 6 `screenshots`, `readme`, `title`,
`known_issues`. Ghost-call's entry used `category: voice`; ours fits `automation` or `tools`.

**Python dependencies**: prefer `pyproject.toml`; every dependency needs an upper bound, floor on the
oldest compatible release; reviewers flag bare floors (`index.md:660-739`, rule 10). Use `uv
--exclude-newer "3 days"` in our CI. `hermes-agent` self-dependencies are dropped. Keep heavy imports
out of `register()`.

**New since ghost-call was pinned (hermes `ed1afb08`, 2026-11-04)**: catalog admission rules are
unchanged (the README at that SHA is identical to `main`). New plugin surfaces since then:
`ctx.register_session_env` (`450ece86c`), plugin JSON-RPC methods + session events (`aa3934771`,
`be3d288fa`), a compression-stable `conversation_id` passed to plugin tools and tool hooks
(`660eb55fc`), `get_session_env` fallback docs (`bce310946`). `PluginContext` moved from
`hermes_cli/plugins.py` (where it is at `v0.23.0`, line 230) to `hermes_cli/plugins_context.py` on
`main`; `from hermes_cli.plugins import PluginContext` stays public. Rule 14 asks for a SemVer
`requires_hermes` in both `plugin.yaml` and the entry, never newer than the current release; ghost-call
declares none. Every API this plugin needs (`ctx.llm` with `task=`, `register_auxiliary_task`,
`call_mcp`, `inject_message`, `post_message`, `ask_choice`, `current_cron_execution`, `oauth:`
with refresh, `register_skill`, `register_automation_blueprint`) exists at `v0.23.0` (checked via
the GitHub API), so `requires_hermes: ">=0.23.0"` is truthful.

## 8. hermes-agent version to pin in CI

- Ghost-call pins `HERMES_AGENT_SHA: ed1afb082eb3e46cf2edae9d8f68fb67b09ee4df` (2026-11-04 21:38 UTC,
  "fix(cli): the prompt's parser drops an image-probe reply that arrives late"). It is **not current**:
  `v0.23.0` (`2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19`, published 2026-11-05) is 615 commits
  ahead of it, and `main` (`cf7003f3fa650e2cebc06a0af0c09dabaf5ee367` at 2026-11-07 08:13 UTC) is 670
  commits ahead of `v0.23.0`.
- Catalog CI (`.github/workflows/plugin-catalog-ci.yml`) validates with **the PR's own hermes
  checkout** (effectively `main` at review time) and runs `hermes plugins validate --install-deps`
  (line 259). It does not run doctor.
- `uv.lock` and `.python-version` (`3.14`) still exist on `main`, so ghost-call's install step
  (`uv sync --frozen --python 3.14`) still works. Hermes also ships a composite action
  `.github/actions/plugin-validate` (inputs `path`, `hermes-ref`, default `main`) that runs validate
  without `--install-deps`.
- Recommendation: a blocking job pinned to `v0.23.0` (`2bd378ed...`, matches `requires_hermes`) and a
  second job on `main` (catches drift before the catalog CI does). Re-check the `main` SHA on
  submission day.

## Design implications for the bookmarks plugin

1. **Scheduling = Hermes cron, not our own loop.** Register two blueprints (`sync` every N hours,
   `weekly-digest` with day/time/deliver slots) and add `/xbm schedule` that creates the jobs via
   `ctx.dispatch_tool("cronjob_manage", ...)` with `enabled_toolsets` = our toolset,
   `skills: ["x-bookmarks:digest"]`, `deliver` from the user, `attach_to_session: true` for the
   digest. Job prompts: "call `xbm_sync`; reply `[SILENT]` unless it reports errors" and "call
   `xbm_digest`; reply with its text verbatim, or `[SILENT]` if it says nothing new". Pin a cheap
   model per job when the user agrees. `/xbm unschedule` and README note: jobs outlive the plugin.
2. **No plugin-owned API key for the LLM.** Use `ctx.llm.complete_structured` with a JSON schema
   (category, tags, summary, action type: read/task/note/skill-candidate, priority) on batches, and
   `ctx.register_auxiliary_task("xbm_classify", inherit_from="compression")` plus one for the digest
   so users can route both to a cheap model. Cache classification per post id in `plugin_db`; never
   reclassify unchanged bookmarks. Show token/cost totals from `result.usage` in `/xbm status`.
3. **X auth.** Preferred: `oauth: - id: x` (authorize `https://x.com/i/oauth2/authorize`, token
   `https://api.x.com/2/oauth2/token`, hosts `[api.x.com]`, public PKCE client, scopes
   `tweet.read users.read bookmark.read offline.access`), sign-in `hermes auth add x-bookmarks:x`,
   all reads through `credentialed_provider_request`. Blocked on exact-port redirects until #149642
   lands; confirm with a real X app tomorrow before building on it. Fallbacks, in order: (a) comment
   on or PR #149642 (`redirect_port` on `oauth:` entries); (b) optional `xurl` CLI backend
   (subprocess, never read `~/.xurl`, disclosed, Linux/macOS); (c) no hand-rolled refresh-token store
   in plugin data — rule 11 forbids it.
4. **Google Docs export** through `oauth: - id: google` (`documents`, `drive.file`, `access_type:
   offline`, `prompt: consent`) with the user's own Desktop client in `optional_env`
   (`XBM_GOOGLE_CLIENT_ID`, `XBM_GOOGLE_CLIENT_SECRET`); do not touch the google-workspace skill's
   token files. **Notion export** through `ctx.call_mcp("notion", ...)` on the optional Notion MCP
   (user adds it with `hermes mcp add`/login and sets `mcp_allowlist`), with an internal-integration
   token fallback. **Local document**: Markdown (and optionally HTML) written to a user-configured
   folder (`config_schema` `export_dir`), defaulting to plugin data; disclose writes outside plugin
   data.
5. **Conversions.** Task and note: our own tables in `plugin_db` (plus optional export of the item).
   Skill: draft a SKILL.md with `ctx.llm`, show it, then create it with `skill_manage` via
   `dispatch_tool` (user-owned, editable). Guard all side-effect tools (`xbm_export`,
   `xbm_make_skill`, `xbm_unbookmark` if any) with `pre_tool_call` -> `approve`; skip the gate only for
   scheduled runs the user enabled in settings, identified by `ctx.current_cron_execution()`.
6. **State**: `plugin_db("x-bookmarks")` for bookmarks, classifications, tasks, notes, digests,
   cursors (`ctx.state` is capped at 10 MiB). No tokens in plugin data.
7. **UI**: `/xbm` subcommands (`sync`, `digest`, `list`, `search`, `export`, `task N`, `note N`,
   `skill N`, `schedule`, `status`, `check`) with `ask_choice` pickers; `config_schema` settings
   (categories list, digest day/time, export targets, auto-export, model notes); a `bookmarks`
   bundled skill; later a Desktop page / transcript directive card and a dashboard tab sharing one
   `plugin_api.py`. Telegram inline buttons only if time allows (needs `in_process` isolation).
8. **Manifest/CI**: `manifest_version: 2`, `requires_hermes: ">=0.23.0"` in both `plugin.yaml` and the
   entry, exact `provides_tools` / `provides_hooks`, `oauth:` client vars in `optional_env` (so the
   plugin still loads without Google), upper-bounded deps (likely none beyond what Hermes ships:
   httpx is already used by Hermes; check before adding). `register()` does no I/O. CI: ruff, pytest
   with a `FakeCtx` that also fakes `llm`, `state`, `call_mcp`, `dispatch_tool`,
   `register_automation_blueprint`, `register_auxiliary_task`, and a seam for
   `credentialed_provider_request` (it refuses callers outside an installed plugin dir), plus
   validate + doctor against `v0.23.0` and `main`.
9. **Disclosure lines to prepare** (rule 13): X API calls with the user's app (and X API billing),
   Google/Notion writes, LLM tokens on the user's provider per sync/digest, cron jobs created and left
   behind after uninstall, files written outside plugin data, no telemetry, no credential-file reads.

## Open questions

1. X callback: does X accept `http://127.0.0.1:<port>/callback` registered with a fixed port only (so
   the random port fails), and will #149642 land soon? Test with a real X app before committing to the
   `oauth:` route.
2. X API access and cost today for `GET /2/users/:id/bookmarks` (tier, pay-per-use price, rate limit,
   `max_results`, the documented cap on how many recent bookmarks are returned) and whether bookmark
   folders (`/bookmarks/folders`) are available to the user's tier.
3. Does `cronjob_manage` accept `enabled_toolsets` naming a plugin toolset, and is the plugin toolset
   enabled for the `cron` platform by default (`hermes tools` -> cron)? What does `deliver: origin`
   resolve to when the job is created from a slash command via `dispatch_tool`?
4. Does `ctx.llm` work unchanged inside cron runs and under `plugins.isolation: host`? (Docs imply yes;
   not verified in code.)
5. Plugin skills in `<available_skills>`: docs say no, `plugins_content.py` says yes. Check at runtime;
   it affects how much our bundled skill costs every session.
6. Notion: is the optional Notion MCP's tool set (create page / append blocks / query database) enough
   for our export shape, and is asking users to edit `mcp_allowlist` acceptable UX?
7. Google OAuth apps in "Testing" status issue refresh tokens that expire after 7 days; document it or
   tell users to publish the app.
8. Do we want Telegram inline buttons on the digest (needs our own platform handler and posting
   path) or is "reply to the continuable digest" enough for v1?
9. Pin choice on submission day: `v0.23.0` or a newer release if one ships before we submit.
