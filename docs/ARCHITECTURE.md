# Architecture (draft for day 1)

Working name: **hermes-x-bookmarks** (package `hermes_x_bookmarks`, slash command `/xbm`).
Sources for every claim below: `docs/research/x-api.md`, `docs/research/destinations.md`,
`docs/research/hermes-platform.md` (hermes-agent main b52b8b00, 2026-11-07).

## What it does

1. **Pull** the user's X bookmarks through the official X API (OAuth 2.0 user login, read-only).
2. **Read** each one fully: long posts (`note_tweet`), X Articles (`article.plain_text`), a post
   that carries an Article as its card, quoted posts, the author's thread around it, link previews.
3. **Sort** with the user's own Hermes model (`ctx.llm`): category, tags, kind, one-line summary,
   status, priority. Cached per post; a bookmark is never classified twice.
4. **Export** to one or more targets: Notion database with a board view, Google Doc, local
   Markdown + a self-contained HTML board on the Desktop.
5. **Act**: weekly digest ("14 threads about agents this week: summary + 3 post ideas"), and turn a
   bookmark into a task, a note or a Hermes skill.

## Components

```
hermes_x_bookmarks/
  __init__.py      register(ctx): tools, /xbm command, hook, blueprints, aux tasks. No I/O.
  config.py        config_schema reading, defaults, categories list
  xapi.py          X API client: bookmarks paging, GET /2/tweets batches, cost meter
  auth.py          token source: Hermes plugin OAuth (preferred) or xurl CLI (fallback)
  reader.py        normalise a post into Item: body text, article, quoted, thread, links, media
  articles.py      Article detection and fetch (cases a, b1, b2) + text clean-up
  classify.py      ctx.llm.complete_structured on batches, JSON schema, cache
  store.py         plugin_db (SQLite): items, classifications, runs, exports, tasks, notes, digests
  digest.py        weekly digest builder (stats + summary + post ideas)
  actions.py       to_task / to_note / to_skill (skill via dispatch_tool("skill_manage"))
  export/
    base.py        Exporter protocol: upsert(items), remove(ids)
    local.py       Desktop folder, Markdown + HTML board (stdlib only)
    notion.py      Notion API 2026-03-11 via httpx (internal integration token) or Notion MCP
    gdocs.py       Drive files.create with HTML -> Google Doc conversion (oauth: google)
  commands.py      /xbm subcommands
  tools.py         agent tools (xbm_*)
  hooks.py         pre_tool_call approval gate for side-effect tools
skills/x-bookmarks/SKILL.md   how the agent should use the tools
```

## X API usage

- Endpoint: `GET /2/users/:id/bookmarks`, scopes `tweet.read users.read bookmark.read offline.access`.
  App-only bearer does not work. Rate limit 180 requests / 15 min per user.
- Request on every call: `tweet.fields=created_at,author_id,conversation_id,lang,entities,
  referenced_tweets,attachments,public_metrics,note_tweet,article`, `expansions=author_id,
  referenced_tweets.id,attachments.media_keys,article.cover_media,article.media_entities`,
  `user.fields=username,name`, `media.fields=url,preview_image_url,alt_text,type`.
  Day 1: check whether the API wants `tweet.fields` or the new `post.fields` names.
- `max_results=90` (one developer saw fewer results at 100). Only the most recent bookmarks are
  reachable: somewhere between ~200 and ~800. Each full run records how many came back.
- Incremental sync: page from newest until we reach a post id we already have.
- Price (owned reads, the user owns the app): **$0.001 per post returned**; expansions on owned
  endpoints probably bill at $0.001 too; from 2026-11-22 media objects bill per item. Resources are
  deduplicated per UTC day. Monthly cap 3M post reads. Other lookups: `GET /2/tweets` $0.005/post.
  Rough cost: first full sync of 800 bookmarks with authors and media ~ $1-3; daily incremental
  syncs ~ cents. `xapi.py` keeps a cost meter per run, shown in `/xbm status`.

## Reading a bookmark (reader.py, articles.py)

Body text priority: `article.plain_text` > `note_tweet.text` > `text`.

| Case | How we detect it | How we get the body |
|---|---|---|
| (a) the bookmark is an Article | `article.title` present | `article.plain_text` from the same response; if missing, `GET /2/tweets?ids=…&tweet.fields=article` |
| (b1) quotes an Article post | `referenced_tweets[type=quoted]` and the quoted post has `article.title` | from `includes.tweets`, else re-fetch the quoted id |
| (b2) Article attached as the card (instead of an image) | `entities.urls[].expanded_url` / `unwound_url` matches `x.com/i/article/<n>` or `x.com/<user>/article/<n>` | try `GET /2/tweets?ids=<n>&tweet.fields=article`, accept only if `article.title` comes back; else keep the link preview (title, description, image) and mark `body_unavailable` |
| long post | `note_tweet` present | `note_tweet.text` |
| thread | `conversation_id != id` or author replies to self | `search/recent` `conversation_id:<id> from:<author>` (last 7 days only); older threads: quoted / replied-to chain only, marked partial |

Clean-up before the LLM and export: strip zero-width characters (U+200B-U+200D, U+2060, U+FEFF;
they can trip Hermes' prompt-injection scanner), normalise Mathematical Alphanumeric bold/italic.
Article text is plain text only (no headings, links, code order); say so in exports.
No scraping, no internal x.com endpoints, no browser automation.

## Classification (classify.py)

- `ctx.llm.complete_structured` with a JSON schema; batches of ~10 items; the user's own model,
  routable to a cheap model through `ctx.register_auxiliary_task("xbm_classify", inherit_from=…)`.
- Output per item: `category` (from the user's list, or "Other" + suggestion), `tags` (≤5),
  `kind` (read / try / post-idea / reference / task / skill-candidate), `summary` (≤160 chars),
  `priority` (1-3), `why_saved` guess.
- Cached by (post id, text hash, schema version). Token totals shown in `/xbm status`.
- Post text is untrusted data: prompts frame it as data; outputs are validated against the schema.

## Storage (store.py)

`plugin_db("hermes-x-bookmarks")` (SQLite WAL under `<HERMES_HOME>/plugin-data/`):
`items` (post id, author, created_at, bookmarked_seen_at, url, text, article_title, article_text,
quoted_id, thread_ids, links json, media json, body_status, deleted_at), `classes`, `exports`
(target, item id, remote id, hash), `tasks`, `notes`, `digests`, `runs` (started, counts, cost).
**No tokens in plugin data** (catalog rule 11).

Deletion compliance (X Developer Policy): when a post disappears or is deleted on X, mark it and
remove or update the copies in Notion / Docs / local on the next sync. Un-bookmarked posts: setting
`on_unbookmark: keep | archive | remove` (default archive).

## Exports

- **Local** (first, no accounts): real Desktop folder (Windows `SHGetKnownFolderPath`
  FOLDERID_Desktop via ctypes, registry fallback, handles OneDrive; macOS `~/Desktop`; Linux
  `xdg-user-dir DESKTOP`). Writes `X Bookmarks/bookmarks.md` (grouped by category) and
  `X Bookmarks/board.html` (self-contained, filter by category/tag/kind, columns by status).
  Optional per-bookmark Obsidian notes with front matter. Folder configurable (`export_dir`).
- **Notion**: internal integration token (`XBM_NOTION_TOKEN`, optional_env) shared with one parent
  page; `Notion-Version: 2026-03-11`. Creates the database and a Board view grouped by Status via
  `/v1/views` (falls back to a one-click manual step). Upsert by `Post ID` (rich_text: 19-digit ids
  lose precision as numbers). Respect 429 Retry-After; ≤100 blocks per append, ≤2000 chars per
  rich text item. Alternative route: the optional Notion MCP through `ctx.call_mcp`.
- **Google Docs**: `oauth: - id: google` with the user's own Desktop client
  (`XBM_GOOGLE_CLIENT_ID/SECRET`, optional_env), scope `drive.file` only (non-sensitive, no
  verification). Build HTML, upload with Drive `files.create` converting to
  `application/vnd.google-apps.document`; re-export replaces the doc content. Consent screen must be
  "In production" or refresh tokens die after 7 days.

Notion database properties: Name (title), Status (status: Inbox / To read / Doing / Done / Archived),
Category (select), Tags (multi_select), Kind (select), Summary (rich_text), Author (rich_text),
Post URL (url), Post ID (rich_text), Bookmarked (date), Posted (date), Has article (checkbox),
Priority (select). Page body: summary, the text or Article body, quote, links, images by URL.

## Hermes surfaces

- **Tools**: `xbm_sync`, `xbm_list`, `xbm_search`, `xbm_get`, `xbm_export`, `xbm_digest`,
  `xbm_to_task`, `xbm_to_note`, `xbm_to_skill`, `xbm_status`.
- **/xbm**: `sync`, `list [category]`, `search <q>`, `export [local|notion|gdocs]`, `digest`,
  `task N`, `note N`, `skill N`, `schedule`, `unschedule`, `status`, `check`.
- **Hook**: `pre_tool_call` asks for approval before `xbm_export` (outside its configured targets)
  and `xbm_to_skill`; scheduled runs the user enabled skip it (`ctx.current_cron_execution()`).
- **Schedules**: plugins have no timer API. `ctx.register_automation_blueprint` for "sync every N
  hours" and "weekly digest"; `/xbm schedule` creates them through
  `ctx.dispatch_tool("cronjob_manage", …)`. Digest job delivers to the user's chosen channel with
  `attach_to_session: true` so the user can reply ("make #3 a task"). Sync job answers `[SILENT]`
  unless something failed. Jobs outlive the plugin: README and `/xbm unschedule` say so.
- **Skill creation**: draft SKILL.md with `ctx.llm`, show it, then `skill_manage` via
  `dispatch_tool` (the skill is user-owned and editable).
- **`ctx.dispatch_tool` skips hooks** (correction, 2026-11-08): it calls `registry.dispatch`
  directly (`tools/registry.py:972` on hermes-agent main 856e7580 and v0.23.0), so the tool's
  availability check, every `pre_tool_call` hook and all middleware are bypassed; only guards inside
  the called tool still run. Our `pre_tool_call` gate covers the model calling `xbm_*` tools, not what
  our code dispatches. Every side effect we reach through `dispatch_tool` (`skill_manage`,
  `cronjob_manage`, file writes, exports) asks for confirmation inside our own code first
  (`ctx.ask_choice` from a slash command; under cron only what the user enabled in settings).
  Reported by a sibling research session; re-check in the code at phase 6.

## X sign-in (the day-1 blocker)

Preferred: Hermes plugin OAuth (`oauth:` in plugin.yaml, `hermes auth add hermes-x-bookmarks:x`,
calls through `credentialed_provider_request`, Hermes stores and rotates the refresh token).
Problem: that flow binds a random 127.0.0.1 port, X wants an exact callback URL. Open issue
NousResearch/hermes-agent#149642 asks for `redirect_port`. Day 1 test order:

1. Register `http://127.0.0.1/callback` and a few fixed-port variants on the X app; see whether X
   accepts a random loopback port (RFC 8252 style). If yes: done.
2. If not: contribute the `redirect_port` change to #149642 (small, upstream, good for the
   hackathon story) and use a local patched Hermes until it merges.
3. Fallback that works today: the `xurl` CLI as token source (subprocess `xurl token`, never read
   `~/.xurl`; disclosed, as the listed x-dashboard plugin does). Downside: xurl asks for write and
   DM scopes.

A hand-rolled token store in plugin data is not allowed (catalog rule 11).

## Policy constraints (X)

- Owned-read price needs the reader to own the developer app. X's Developer Policy warns against
  "requiring your end users to register applications" for a tool; X staff told one developer that a
  kit where each user creates their own app is not permitted, and suggested one app that users
  authorize. With one shared app, other users' reads bill to the app owner at standard rates.
  Decision needed: see `docs/DECISIONS.md` D1.
- Sending post text to an LLM is not named in the Developer Agreement, but staff say a new purpose
  like that must be declared in the app's use case and approved. Put it in the use case text.
- No model training on X content; keep copies in sync with deletions.
