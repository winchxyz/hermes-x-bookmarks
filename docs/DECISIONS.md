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
- **Expansions (2026-11-08):** no `article.media_entities` by default (half of all billable
  expanded resources after 2026-11-22); incremental syncs use small pages and stop at known ids.

- Official X API only. No scraping, internal x.com endpoints or browser automation.
- LLM through the user's Hermes model (`ctx.llm`); no plugin-owned AI key.
- Local export ships first (works with no accounts), then Notion, then Google Docs.
- Google Docs via Drive HTML upload with conversion, scope `drive.file` only.
- No tokens in plugin data (catalog rule 11). Hermes or xurl hold them.
- Schedules are Hermes cron jobs created from blueprints / `/xbm schedule`, not our own loop.
- httpx for every HTTP API; no vendor SDKs.
- Article bodies are plain text from the API; exports say so.
