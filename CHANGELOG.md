# Changelog

## 0.2.0 (2026-11-09)

Exports to Obsidian, Notion and Google Docs.

- `export obsidian`: one note per bookmark with front matter and the full text, plus an
  `X Bookmarks.base` table; finds the open vault itself; re-exports update only the plugin's
  keys and keep your status, keys and writing.
- `export notion`: database with boards by category and by status, one page per bookmark;
  updates only what changed, never touches Status, never re-creates pages you deleted;
  2.5 requests/s with Retry-After. Token `XBM_NOTION_TOKEN`.
- `export gdocs`: one Google Doc grouped by category, rewritten in place; Hermes sign-in
  `hermes auth add hermes-x-bookmarks:google` with your own Desktop client, scope `drive.file`.
- `export` takes targets (`desktop obsidian notion gdocs all`), default from `export_to`.
- README lists what the plugin reads, writes and calls.

## 0.1.0 (2026-11-09)

First release: sync, sort and a Desktop board.

- X sign-in with the four keys of your own X app (OAuth 1.0a), read through Hermes' secret scope;
  Hermes OAuth 2.0 and the `xurl` CLI as options.
- `sync`: full first run, then small pages that stop at stored bookmarks; X Article bodies and
  long posts inline; quoted Articles kept; every page stored as it arrives, rate limits recorded.
- `classify`: your Hermes model on the plugin's own slot `xbm_classify`; category, tags, kind,
  summary, priority, why-saved; category boundaries, `about_me` for priority, cache by text and
  prompt version, JSON-mode fallback, stops after repeated failures.
- `export`: `X Bookmarks/board.html` (self-contained board) and `bookmarks.md` on your Desktop.
- `status`, `list [N] [category]`, `about`; the same commands as `/xbm` in chat and `hermes xbm`
  in the terminal.
