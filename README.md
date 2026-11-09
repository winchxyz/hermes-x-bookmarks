# hermes-x-bookmarks

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that reads all your X
bookmarks, including long posts, threads and X Articles, sorts them with your own Hermes model and
puts them on a board on your Desktop.

```
/xbm sync       pull your bookmarks from X (the first run reads all of them)
/xbm classify   sort them: category, tags, kind, one-line summary, priority
/xbm export     write "X Bookmarks/board.html" and "bookmarks.md" to your Desktop
```

Works in any Hermes chat (`/xbm ...`) and in the terminal (`hermes xbm ...`).
Uses the official X API only: no scraping, no browser automation, read-only access.

## What v0.1 does

- **Sync.** Reads every bookmark the X API returns, newest first. The full text of X Articles
  (your bookmark is the Article, or quotes one) and long posts comes with it. Later syncs read small
  pages and stop as soon as they reach bookmarks already stored.
- **Sort.** Your Hermes model labels each bookmark: a category from your list, up to 5 tags, a kind
  (read, try, task, post-idea, reference, skill-candidate), a one-sentence summary, a priority
  (1-3) and why you probably saved it. Ten bookmarks per model call; nothing is sorted twice.
  Post text is passed to the model as data, never as instructions.
- **Board.** `board.html` is one self-contained page: search, filters, columns by category,
  kind or priority, a "done" mark per card (kept in that browser). `bookmarks.md` is the same
  list as Markdown, grouped by category.

Coming next: Notion and Google Docs export, a weekly digest through Hermes cron, and turning a
bookmark into a task, note or Hermes skill. See [docs/PLAN.md](docs/PLAN.md).

## Setup

### 1. Your own X developer app

Every user brings their own X app and pays X for their own reads; nothing goes through a shared
app.

1. Sign in at [console.x.com](https://console.x.com) with the X account whose bookmarks you want.
   That account must own the app (that is what makes the "owned reads" price apply).
2. Create an app on the **Pay-per-use** plan, add credit and set a spending limit.
3. In the app's user authentication settings, set permissions to **Read**.
4. On **Keys and tokens**, copy the **API Key** and **API Key Secret**, then generate the
   **Access Token** and **Access Token Secret** (after setting Read, so they carry it).

### 2. Keys into Hermes

Put the four values in your Hermes profile's `.env` (`~/.hermes/.env`; on Windows
`%LOCALAPPDATA%\hermes\.env`):

```
XBM_X_API_KEY=...
XBM_X_API_SECRET=...
XBM_X_ACCESS_TOKEN=...
XBM_X_ACCESS_TOKEN_SECRET=...
```

The plugin reads them through Hermes' secret scope and never writes them anywhere. To revoke,
regenerate the tokens on X.

### 3. Install

```bash
hermes plugins install winchxyz/hermes-x-bookmarks --enable
hermes xbm whoami
```

`whoami` should print your handle. Then:

```bash
hermes xbm sync
hermes xbm classify --all
hermes xbm export
```

## Settings

Set in the Hermes Plugins settings, or with `/xbm about` for the last one.

| Setting | Default | What it does |
|---|---|---|
| `categories` | AI & agents, Coding & dev tools, Crypto & web3, Business & growth, Design & art, Learning & guides, News & opinion, Life & misc | Your category list, comma-separated. "Other" is always added. |
| `classify_language` | English | Language of summaries and the why-saved note |
| `about_me` | empty | A sentence on what you build and follow; used only to judge priority (`/xbm about <text>`) |
| `export_dir` | `X Bookmarks` on your Desktop | Where `export` writes |
| `auth_backend` | auto | `keys` (above), `hermes` (OAuth 2.0 via `hermes auth add hermes-x-bookmarks:x`) or `xurl` |

Sorting runs on the plugin's own model slot, **X bookmarks: sorting**. It uses your main model
until you pick another one in `hermes model` (auxiliary tasks). A stronger model gives clearly
better priorities and fewer odd categories.

## Commands

| Chat | Terminal | |
|---|---|---|
| `/xbm sync [full]` | `hermes xbm sync [--full]` | Pull new bookmarks (`full` re-reads all) |
| `/xbm classify [N\|all]` | `hermes xbm classify [--limit N \| --all]` | Sort unsorted bookmarks (chat: 20 by default, max 100) |
| `/xbm export` | `hermes xbm export [--dir PATH]` | Write the board and the Markdown file |
| `/xbm status` | `hermes xbm status` | Counts, categories, last runs, X API and model use |
| `/xbm list [N] [category]` | `hermes xbm list [--limit N] [--category C]` | Most recent bookmarks with their labels |
| `/xbm about [text\|clear]` | `hermes xbm about [text]` | Show or set what you build and follow |

## Cost

- **X API** (paid to X, on your app). Reading your own bookmarks is an "owned read": about
  **$0.001 per post**. The author's first full sync of 1,880 bookmarks took 22 requests and about
  **$1.89**; a sync with nothing new reads 10 posts, about $0.01. From 2026-11-22 X also bills
  the expanded objects that come with each page (authors, images, quoted posts): on the same
  1,880 bookmarks that is about 3,650 more objects, so a full sync costs roughly 3x.
  `/xbm status` shows an estimate per run.
- **Model** (your provider). Sorting 1,880 bookmarks took 188 calls, about 500k input and 200k
  output tokens. On a free model that was $0.

## Privacy and limits

- Your bookmarks, labels and run history live in Hermes plugin data (SQLite) on your machine.
  No keys or tokens are stored there.
- Post text goes to the model you configured in Hermes, and nowhere else.
- The board and Markdown file contain post text; they stay where you export them.
- X Article bodies come from the API as plain text (no headings, links or images inside).
- Threads: each bookmarked post is stored on its own; the rest of the thread is not fetched yet.
- Removing a bookmark on X does not yet remove it here.

## Development

```bash
pip install -e . -r requirements-dev.txt
ruff check .
pytest -q
```

Design and research notes: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
[docs/DECISIONS.md](docs/DECISIONS.md), [docs/research/](docs/research/).
CI runs ruff, pytest, and `hermes plugins validate` / `doctor` against Hermes v0.23.0 and main.

## License

MIT
