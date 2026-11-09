# Decisions

## Open (need the owner)

**D1. Who runs it: settled 2026-11-09.** Every user brings their own X developer app and keys
and pays X for their own reads. The owner does not run a shared app and does not pay for anyone
else's reads (option "one app for everyone" is out, 2026-11-08). Registering an app and paying for
it is each user's own choice, so D1b (asking X about bring-your-own-app) is closed and does not
hold back the catalog submission (owner, 2026-11-09).

**D2. X sign-in route: settled 2026-11-08** (see "Made" below).

**D3. Notion route: changed 2026-11-09 (0.2.1).** Default is Hermes' own Notion connector: the
`notion` MCP server from `hermes mcp install notion`, called through `ctx.call_mcp` once the
user lists it in `plugins.entries.hermes-x-bookmarks.mcp_allowlist` (owner: use Hermes' own
connectors where they exist). The connection token `XBM_NOTION_TOKEN` (plain httpx to `api.notion.com`) stays
as the fallback (see "Made" below).

**D4. Product name.** Working name hermes-x-bookmarks / `/xbm`.

## Made

- **D2, X sign-in (2026-11-08, day-1 spike, gate passed).** Default route: OAuth 1.0a user
  context with the four keys of the user's own X app (API Key/Secret, Access Token/Secret from
  Keys and tokens) in the Hermes profile's `.env`, read through `agent.secret_scope`, each GET
  signed with HMAC-SHA1 (`oauth1.py`). Works live on `users/me` and the bookmarks endpoint. No
  browser sign-in, no callback URL, tokens do not expire; the user revokes by regenerating them
  on X. Kept as options: Hermes plugin OAuth 2.0 (`hermes auth add hermes-x-bookmarks:x`), which
  still binds a random loopback port in Hermes v0.23.0 (no `redirect_port`, hermes-agent#149642),
  and the `xurl` CLI. Not tested live: whether X accepts the random port.
- **Article bodies (2026-11-08, live):** `article.plain_text` arrives inline for Article bookmarks
  (161/161) and for quoted Articles in `includes.tweets` (32/32). The number in
  `x.com/i/article/<n>` is not a post id; never look it up. Code blocks come in
  `article.entities.code`. Details: `docs/research/x-api.md`, "Day-1 live results".
- **Phase 2 gate passed (2026-11-08, live):** first `hermes xbm sync` stored 1,880 bookmarks
  (213 Articles, all with full text) to the end of the list; the second sync made 1 request
  (20 posts, ~$0.02), found 0 new and stopped as caught up.
- **Phase 3 first full run (2026-11-09, live):** 1,880 bookmarks sorted in 188 calls on the
  owner's free default model (upstage/solar-mini4:free), 462k tokens in / 240k out, $0, no
  failed call. After the per-block rule and about-me: `--sref` posts read as Midjourney style
  codes, the owner's own posts are recognised, no repeated summaries. Weak spots of this small
  model: why_saved often parrots the about-me text, and about-me pulls some crypto posts into
  "AI & agents". A stronger model on the `xbm_classify` slot is the fix; owner review pending.
- **Phase 3 re-sort with category boundaries (2026-11-09, live, label schema 3):** same free
  model, 188 calls, 501k / 198k tokens, $0. why_saved parroting the about-me text 21% -> ~0%;
  302 of 1,880 categories changed, mostly toward the right one (memecoin how-to and Solana jobs
  -> crypto, AI mascot design -> design, Claude Code Security -> dev tools). Still weak:
  priority is 75% p2, and a few odd cases remain (Telegram NFT guide in "AI & agents").
- **Expansions (2026-11-08):** no `article.media_entities` by default (half of all billable
  expanded resources after 2026-11-22); incremental syncs use small pages and stop at known ids.

- Official X API only. No scraping, internal x.com endpoints or browser automation.
- LLM through the user's Hermes model (`ctx.llm`); no plugin-owned AI key.
- Local export ships first (works with no accounts), then Notion, then Google Docs.
- Google Docs via the Docs API (create + batchUpdate), scope `drive.file` only. Changed from
  the planned Drive HTML upload (2026-11-09): Hermes' `credentialed_provider_request` sends JSON
  bodies only, so a multipart upload is impossible without holding the token ourselves (rule 11).
  The same document is rewritten in place (delete range + insert), so its link stays.
- Notion, connector route (0.2.1): `notion-create-database` (SQL DDL schema), two
  `notion-create-view` boards, `notion-create-pages` 25 at a time (SQLite-form properties,
  Notion-flavored Markdown body with every Markdown character escaped), `notion-update-page`
  `update_properties` for changes. Hermes owns the Notion OAuth; the plugin holds nothing.
  Live 2026-11-09 (0.2.2, chat through the gateway): database and boards created, 300 pages in
  one chat export, all 300 page ids read back (distinct). The connector rejects select and
  multi-select values that are not options yet; 0.2.2 learns the allowed values from that error.
  0.2.3 (no page cap in chat): all 1,880 bookmarks in Notion, 1,880 distinct page ids, no
  duplicates. Not checked: whether `hermes xbm ...` in a terminal reaches the connector. The gateway loads
  plugin code once: after a plugin update, `hermes gateway restart`.
- Notion, token route: `api.notion.com` with the user's connection token from the secret scope
  (`XBM_NOTION_TOKEN`). Export state (item -> page id, content hash) lives in the plugin
  database and is shared by both routes, so unchanged pages cost no request.
- Google stays on the plugin's own `google` OAuth entry: Hermes has no Google Docs connector
  (its hosted connectors are Nous Portal features with no plugin API).
- Obsidian notes are found again by `tweet_id` front matter, not by file name; only the
  plugin's keys are rewritten.
- No tokens in plugin data (catalog rule 11). Hermes or xurl hold them.
- Schedules are Hermes cron jobs created from blueprints / `/xbm schedule`, not our own loop.
- httpx for every HTTP API; no vendor SDKs.
- Article bodies are plain text from the API; exports say so.
