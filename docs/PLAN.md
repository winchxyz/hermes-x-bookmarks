# Build plan

Each phase ends with a gate: the listed check must pass before the next phase starts.

## Day 1 — spike, then the core

**1. X spike (go / no-go, ~1 h).** Owner finished `docs/SETUP.md` section 1.
- Sign in with the X app: first through Hermes plugin OAuth (random loopback port), then a fixed
  port, then `xurl` as the fallback. Record which works (D2).
- Pull the bookmarks with the field set from ARCHITECTURE.md. Check `tweet.fields` vs `post.fields`.
- Save the raw responses for the test bookmarks as anonymised fixtures in `tests/fixtures/`
  (strip names and handles of other people where not needed).
- Answer with real data: does `article.plain_text` come back in the bookmarks call, in
  `includes.tweets` for a quoted Article, and for an `x.com/i/article/<n>` link via
  `GET /2/tweets?ids=<n>`? How many bookmarks does a full run return? What did it cost?
- Gate: bookmarks come back with Article text for case (a). Otherwise stop and rethink.

**2. Core.** `xapi.py`, `auth.py`, `reader.py`, `articles.py`, `store.py` with unit tests on the
fixtures; `register()`, `/xbm sync`, `/xbm status`, `/xbm list`. CI green (ruff, pytest,
validate + doctor on v0.23.0 and main).
- Gate: `/xbm sync` in a real Hermes stores the bookmarks; a second sync fetches only new ones.

## Day 2 — sorting and the local document

**3. Classification.** `classify.py` with `ctx.llm.complete_structured`, cache, aux task, token
totals. Tests with a fake `ctx.llm`. Real run on the owner's bookmarks; owner reviews 20 results.
- Gate: categories look right to the owner; nothing classified twice.

**4. Local export.** Desktop path finder, `bookmarks.md`, `board.html` (self-contained, filters,
columns by status). Screenshot of the board for the owner.
- Gate: the owner opens the board from the Desktop and likes it.

## Day 3 — Notion, digest, actions

**5. Notion.** Database create, Board view via `/v1/views`, upsert by Post ID, page bodies,
429 handling, deletion sync. Tests with recorded responses.
- Gate: the board shows in the owner's Notion grouped by Status; re-export makes no duplicates.

**6. Digest and actions.** `digest.py` (week stats, summary, 3 post ideas), `xbm_to_task`,
`xbm_to_note`, `xbm_to_skill` (draft, show, `skill_manage`), approval hook, blueprints and
`/xbm schedule`.
- Gate: a scheduled digest reaches the owner's chat and a reply turns item #3 into a task.

## Day 4 — Google Docs, polish, release

**7. Google Docs.** `oauth: google`, HTML build, Drive upload with conversion, replace on re-export.
**8. Release.** README with honest disclosure, demo, catalog entry draft. Publish only after D1
(personal tool vs product) is settled.

## Not in v1

Bookmark folders (20 folders x ~20 posts, no paging), un-bookmarking (`bookmark.write`),
Telegram inline buttons, Desktop/dashboard page, Google Sheets.
