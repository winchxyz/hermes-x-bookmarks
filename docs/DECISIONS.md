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

**D2. X sign-in route.** Hermes plugin OAuth if X accepts a random loopback port, else upstream
`redirect_port` (hermes-agent#149642), else the `xurl` CLI. Settled by the day-1 spike.

**D3. Notion route.** Internal integration token (simple, our code) vs the optional Notion MCP
(`ctx.call_mcp`, no token in our plugin, but the user edits `mcp_allowlist`). Default: token;
MCP as an option if its tool set covers database create + view + upsert.

**D4. Product name.** Working name hermes-x-bookmarks / `/xbm`.

## Made

- Official X API only. No scraping, internal x.com endpoints or browser automation.
- LLM through the user's Hermes model (`ctx.llm`); no plugin-owned AI key.
- Local export ships first (works with no accounts), then Notion, then Google Docs.
- Google Docs via Drive HTML upload with conversion, scope `drive.file` only.
- No tokens in plugin data (catalog rule 11). Hermes or xurl hold them.
- Schedules are Hermes cron jobs created from blueprints / `/xbm schedule`, not our own loop.
- httpx for every HTTP API; no vendor SDKs.
- Article bodies are plain text from the API; exports say so.
