# Changelog

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
