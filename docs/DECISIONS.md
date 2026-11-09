# Decisions

## Open (need the owner)

**D1. Who runs it: a personal tool or a product others install?**
X prices "owned reads" ($0.001/post) only when the reader owns the developer app, and X's
Developer Policy warns against tools that make every end user register their own app.
- (a) Personal-first (recommended for now): the owner's own app, own bookmarks. The public repo is
  "how I built my personal integration". Catalog submission waits until D1b is settled.
- (b) One app that other users authorize with OAuth: compliant, but the owner pays standard rates
  ($0.005/post + expansions) for everyone's reads.
- D1b: ask X on devcommunity.x.com whether a Hermes plugin where each user brings their own app is
  acceptable (owner posts; draft the question on day 1).

2026-11-08, owner: option (b) is out. The owner does not pay for other users' reads; every user
brings their own X app and keys and pays X for their own reads. The policy question of D1b stays
open for a catalog submission.

**D2. X sign-in route: settled 2026-11-08** (see "Made" below).

**D3. Notion route.** Internal integration token (simple, our code) vs the optional Notion MCP
(`ctx.call_mcp`, no token in our plugin, but the user edits `mcp_allowlist`). Default: token;
MCP as an option if its tool set covers database create + view + upsert.

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
- Notion talks to `api.notion.com` with the user's connection token from the secret scope
  (`XBM_NOTION_TOKEN`); no Notion OAuth. Export state (item -> page id, content hash) lives in
  the plugin database, so unchanged pages cost no request.
- Obsidian notes are found again by `tweet_id` front matter, not by file name; only the
  plugin's keys are rewritten.
- No tokens in plugin data (catalog rule 11). Hermes or xurl hold them.
- Schedules are Hermes cron jobs created from blueprints / `/xbm schedule`, not our own loop.
- httpx for every HTTP API; no vendor SDKs.
- Article bodies are plain text from the API; exports say so.
