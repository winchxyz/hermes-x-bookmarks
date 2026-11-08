# Export destinations research: Notion, Google Docs, local Desktop file

Researched 2026-11-07 for the x-bookmarks Hermes plugin (Python). Every fact carries a source and a confidence tag:

- **[official]**: vendor documentation (developers.notion.com, developers.google.com, learn.microsoft.com, support.google.com).
- **[secondary]**: third-party docs, source code of a library, community posts, man pages.
- **[unverified]**: my inference or memory, not confirmed by a source fetched today.
- **[verified locally]**: tested on this Windows machine today.

---

## Notion

### 1. API version, data sources, creating the database, property types

**Current version.** Two dated versions matter: `2025-09-03` (introduced data sources) and `2026-03-11` (the newest; used in all current examples). No newer `Notion-Version` is listed. [official] https://developers.notion.com/reference/versioning

`2026-03-11` changes (all small, but they affect our payloads) [official] https://developers.notion.com/docs/upgrade-guide-2026-03-11:
- `archived` is renamed `in_trash` on pages, databases, blocks and data sources.
- Append block children: `after` is replaced by `position` (`{"type": "after_block", "after_block": {"id": ...}}`, `"start"`, or `"end"`; default `end`).
- Block type `transcription` is renamed `meeting_notes`.

Also: since June 2026, `url` fields on pages/databases/data sources return `https://app.notion.com/p/{id}` instead of `www.notion.so` links; old links still open. Store ids, never parse URLs. [official] https://developers.notion.com/page/changelog

**The data sources model (2025-09-03 and later).** A *database* is now a container; its schema and rows live in one or more *data sources*. [official] https://developers.notion.com/docs/upgrade-guide-2025-09-03
- Create: `POST /v1/databases`, with the schema under `initial_data_source.properties`, and `title`, `icon`, `cover`, `is_inline`, `parent` at database level.
- Query: `POST /v1/data_sources/{data_source_id}/query` (no longer `/v1/databases/{id}/query`). [official] https://developers.notion.com/reference/query-a-data-source
- Create rows: `POST /v1/pages` with `"parent": {"type": "data_source_id", "data_source_id": "..."}`.
- Search: `filter.value` is `"page"` or `"data_source"` (not `"database"`).
- Webhook events renamed `data_source.content_updated`, `data_source.schema_updated`, etc.

**Create the database under a page the integration can access** [official] https://developers.notion.com/reference/create-database:
- `parent` must be `{"type": "page_id", "page_id": "..."}` for an internal connection (the schema also allows `workspace: true`, which only OAuth/user-owned tokens can use; see section 5).
- Returns 404 if the parent page does not exist *or is not shared with the connection*; 403 if the connection lacks insert-content capability.
- The response has `id` (database id) and `data_sources[0].id` (data source id). **Persist both**: rows and queries need the data source id, views need both. [official] https://developers.notion.com/guides/get-started/preparing-for-users
- `database_type` (`tasks`, `projects`, `skills`) cannot be combined with `initial_data_source` (400).

Request sketch (version `2026-03-11`):

```json
POST /v1/databases
{
  "parent": {"type": "page_id", "page_id": "<shared page id>"},
  "title": [{"type": "text", "text": {"content": "X Bookmarks"}}],
  "icon": {"type": "emoji", "emoji": "🔖"},
  "initial_data_source": {
    "properties": {
      "Name":     {"title": {}},
      "Tweet ID": {"rich_text": {}},
      "URL":      {"url": {}},
      "Category": {"select": {"options": [{"name": "Agents", "color": "purple"}]}},
      "Tags":     {"multi_select": {}},
      "Type":     {"select": {"options": [{"name": "Read"}, {"name": "Try"}, {"name": "Post idea"}, {"name": "Reference"}]}},
      "Status":   {"status": {"options": [
                     {"name": "Inbox", "color": "gray", "group": "To-do"},
                     {"name": "In progress", "color": "blue", "group": "In progress"},
                     {"name": "Done", "color": "green", "group": "Complete"},
                     {"name": "Archived", "color": "default", "group": "Complete"}]}},
      "Posted":   {"date": {}}
    }
  }
}
```

**Which property types can be created via the API (as of today)** [official] https://developers.notion.com/reference/property-object:

| Type | Create via API? | Notes |
|---|---|---|
| title | yes | exactly one per data source |
| rich_text | yes | |
| url | yes | |
| date | yes | |
| select / multi_select | yes | option names unique case-insensitively; **commas not allowed** in option names |
| **status** | **yes, now** | Read-only schema until 2026; the changelog (2026-03-19) says status can now be created and updated via the API. `status: {}` creates default options `Not started`, `In progress`, `Done` in groups `To-do`, `In progress`, `Complete`. Custom options may set `"group"` to one of those three group names (added 2026-06-22). Group definitions themselves can only be managed in the Notion app. A read-only `default_option` appears in schemas since 2026-10-22. [official] https://developers.notion.com/page/changelog |
| people | yes | not useful for a single-user plugin |
| relation | yes | needs the target data source id |
| files | yes | page values can be external URLs |
| number, checkbox, email, phone_number, place | yes | |
| formula, rollup, unique_id, created_time, last_edited_time, created_by, last_edited_by | schema yes, values read-only | |
| button, verification | **no** | API ignores/rejects them |

Pitfall: **do not store the tweet id as a `number`**. Tweet ids are 19-digit integers, larger than 2^53, and Notion numbers are JSON numbers (floats), so ids would lose precision. Use `rich_text`. [unverified, standard IEEE-754 reasoning]

### 2. Views: yes, the API can now create a board

This changed in 2026. **A views API launched 2026-03-19** with endpoints to create, read, update, delete, list and query views. [official] https://developers.notion.com/page/changelog, https://developers.notion.com/guides/data-apis/working-with-views

Endpoints [official] https://developers.notion.com/guides/data-apis/working-with-views:
- `GET /v1/views?database_id=...` or `?data_source_id=...` (references only), `GET /v1/views/{view_id}` (full config)
- `POST /v1/views`, `PATCH /v1/views/{view_id}` (partial), `DELETE /v1/views/{view_id}` (irreversible; the last view of a database cannot be deleted)
- `POST /v1/views/{view_id}/queries`, then `GET .../queries/{query_id}` to page through; queries expire after about 15 minutes.

**Default view:** creating a database via the API provisions one data source and one **Table view named "Default view"**. [official] same guide

`POST /v1/views` body [official] https://developers.notion.com/reference/create-view:
- Required: `data_source_id`, `name`, `type`, plus exactly one of `database_id` (a tab on the database), `view_id` (a dashboard widget) or `create_database` (a linked view on a page).
- `type` enum: `table`, `board`, `list`, `calendar`, `timeline`, `gallery`, `form`, `chart`, `map`, `dashboard`.
- `filter` uses the data source query filter format (compound nesting up to 2 levels); `sorts` up to 100; `quick_filters` render as pills above the view.
- Board `configuration` requires `group_by`:
  - status: `{"type": "status", "property_id": "<id>", "group_by": "option" | "group", "sort": {"type": "manual"}, "hide_empty_groups": false}`
  - select / multi_select: `{"type": "select", "property_id": "<id>", "sort": {"type": "manual" | "ascending" | "descending"}, "hide_empty_groups": true}` (no inner `group_by`)
  - optional board settings: `sub_group_by`, `properties` (visible card properties), `cover`, `cover_size`, `cover_aspect`, `card_layout`.
- Needs insert-content and update-content capabilities on the connection.

Board example (from the official guide, shape):

```json
POST /v1/views
{
  "database_id": "<db id>",
  "data_source_id": "<ds id>",
  "name": "Board",
  "type": "board",
  "configuration": {
    "type": "board",
    "group_by": {"type": "status", "property_id": "<Status property id>", "group_by": "option", "sort": {"type": "manual"}}
  }
}
```

Plan: after creating the database, create **"Board"** (status, by option) and **"By category"** (select `Category`), then optionally `PATCH` the auto-created "Default view" to rename it "All" with a sort by `Posted` descending. Property ids come from the data source schema (`GET /v1/data_sources/{id}`).

Version caveat: the create-view reference says the only allowed `Notion-Version` is `2026-03-11`, while the guide says "2025-09-03 or later". **Send `2026-03-11` for everything.** [official, conflicting pages] Also, the create-data-source reference still says view management is not supported *in that endpoint*; it is done through `/v1/views`.

Fallback if the views call fails (old token, wrong version): the user opens the database, clicks **+ Add view → Board**, and picks **Group by: Status**. Document this in the setup guide. [unverified UI wording]

### 3. Upsert without duplicates

Notion has no native upsert or unique constraint. Pattern:

1. Keep a local state file (`tweet_id -> notion_page_id`, plus a content hash). This avoids most queries.
2. If unknown locally, query the data source by the `Tweet ID` rich_text property:
   ```json
   POST /v1/data_sources/{ds_id}/query
   {"filter": {"property": "Tweet ID", "rich_text": {"equals": "1854321098765432109"}}, "page_size": 1}
   ```
   `rich_text` filter conditions: `equals`, `does_not_equal`, `contains`, `does_not_contain`, `starts_with`, `ends_with`, `is_empty`, `is_not_empty`. [official] https://developers.notion.com/reference/filter-data-source-entries. A `url` property can be filtered the same way (`{"property": "URL", "url": {"equals": ...}}`) per older docs; the current filter page no longer lists url explicitly. [secondary] Prefer the id; URLs vary (`x.com` vs `twitter.com`, `?s=20`).
3. Found: `PATCH /v1/pages/{id}` with only the properties the plugin owns. **Never overwrite `Status`** on update, because the user moves cards on the board; set it only on create.
4. Not found: `POST /v1/pages`.
5. Bulk alternative for first sync: page through the whole data source once with `filter_properties=Tweet ID` (query parameter; returns only that property) and build the map. [official] https://developers.notion.com/reference/query-a-data-source

Pagination [official] https://developers.notion.com/reference/pagination, https://developers.notion.com/reference/query-a-data-source:
- `page_size` 1 to 100 (default 100); response `has_more` + `next_cursor`, pass as `start_cursor`.
- A single query returns at most **10,000 results**, then `request_status.type` is `incomplete` (`query_result_limit_reached`). Partition by `created_time` if a user ever exceeds that.
- In-trash rows are excluded unless `is_archived: true`; a row the user deleted will not be found and would be recreated. Decide: the local state file should remember "deleted by user" and not re-add. [unverified design note]

Batch writes: none. One page per request. Combine properties and body in the create call to keep it to one request per new bookmark.

### 4. Limits and 429 handling

[official] https://developers.notion.com/reference/request-limits
- Per connection: **180 requests per minute (about 3/s average)** on Free/Plus, **600/min (about 10/s)** on Business and Enterprise, in a fixed 60-second window (since 2026-09-09).
- Plus a per-workspace budget shared by all connections (no number published; its `Retry-After` can exceed 60 s), and a separate limit of about 3 requests/s per connection for data source queries.
- 429 `rate_limited` and 529 `service_overload`: honour the integer-seconds `Retry-After` header (also repeated in the body since 2026-09-24); for the per-connection limit it is at most 60 s. Use exponential backoff with jitter and a retry cap. Do not retry a 429 with code `public_api_request_blocked`.
- Size limits per request: rich text `text.content` **2000 characters** per item; link URL 2000; any URL 2000; arrays (blocks per append, rich text items) **100 elements**; multi_select 100 options, relation 100, people 100; whole payload **1000 block elements and 500 KB**. Violations are 400 `validation_error`.
- Markdown body on page create: more than 5000 blocks (nested counted) fails; keep pages small. [official] https://developers.notion.com/guides/data-apis/working-with-markdown-content

Implementation: a token-bucket limiter at 2.5 req/s plus Retry-After honouring is enough. Split long text into 2000-char rich-text chunks (a paragraph can hold up to 100 chunks).

### 5. Auth: which token

Three options exist now [official] https://developers.notion.com/guides/connections-and-tokens/overview, https://developers.notion.com/docs/authorization:

| | Internal connection | Personal access token (PAT) | Public connection (OAuth) |
|---|---|---|---|
| Acts as | its own bot user | the user who created it | each authorizing user |
| Content access | only pages shared with it | all pages the user can see, limited by token capabilities | pages chosen at OAuth time |
| Who can create | workspace owner (Developer portal) | per plan: Free/Business default owners only, Plus all members; admins can change and revoke | app developer; review only for Marketplace |
| Expiry | static until revoked | 7 d / 30 d / 90 d / 180 d / 1 y, default 1 y (2026-07-02) | access + refresh token |
| Workspace-level (no parent) pages | no | not stated | yes (go to user's Private section) |

- PATs launched 2026-05-12 and the docs recommend them "for scripts, CLI workflows, Workers, and trusted tools". [official] https://developers.notion.com/page/changelog, https://developers.notion.com/guides/get-started/create-a-notion-integration (created at https://www.notion.so/developers/tokens).
- Token format: new tokens use the `ntn_` prefix since 2024-09-25; old `secret_` tokens keep working. [official] changelog. Treat the token as opaque; do not validate the prefix.
- Sharing a page with an internal connection: page **••• → Add connections → pick the connection**, or the connection's Content access tab in the Developer portal. [official] https://developers.notion.com/docs/authorization, https://developers.notion.com/guides/connections-and-tokens/internal-connections
- OAuth: `https://api.notion.com/v1/oauth/authorize?client_id=...&redirect_uri=...&response_type=code&owner=user`, token at `/v1/oauth/token` with Basic auth; refresh tokens exist. Requires a hosted redirect and a client secret, overkill here. [official] https://developers.notion.com/docs/authorization

**Recommendation for a self-hosted single-user plugin: internal connection token** as the default. Reasons: least privilege (sees only the one page the user shares), no expiry surprises, works on every plan. Setup: create connection, enable Read/Update/Insert content, share one parent page "X Bookmarks", paste token + page URL into the plugin config. Accept a PAT too (same `Authorization: Bearer` header); mention that a PAT expires (default 1 year) and sees everything the user sees. Skip OAuth.

### 6. Page body: summary, quote, tweet link, images

Two ways to write the body:

**A. Blocks (`children` on create, or `PATCH /v1/blocks/{id}/children`)** [official] https://developers.notion.com/reference/block
- Summary: `callout` (`rich_text`, `icon`, `color`) or `paragraph`.
- Tweet text: `quote` block (`rich_text`, children allowed). Chunk at 2000 chars.
- Link to the tweet: `bookmark` `{"url": "https://x.com/user/status/ID", "caption": []}` (reliable link card). `embed` `{"url": ...}` exists, but the docs do not say whether X/Twitter URLs render as a live tweet embed via the API. [official for shapes; tweet rendering unverified] Use bookmark by default; offer embed as an option after a manual test.
- Images by external URL: `{"type": "image", "image": {"type": "external", "external": {"url": "..."}}}`. The URL must be publicly reachable, point directly at the file (no redirector), and end in a supported extension (`.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.heic`, `.bmp`, `.tif`, `.tiff`). X media URLs like `https://pbs.twimg.com/media/<key>.jpg` fit; the `?format=jpg&name=large` form does not have an extension. [official rules; X URL shape secondary]
- Paragraph with a link: rich text `{"type": "text", "text": {"content": "...", "link": {"url": "..."}}}`.
- Up to 100 blocks per request, so one request per bookmark is fine.

**B. Markdown (`markdown` on `POST /v1/pages`)**, launched 2026-02-26 [official] https://developers.notion.com/guides/data-apis/working-with-markdown-content, https://developers.notion.com/reference/post-page
- Mutually exclusive with `children`; can be combined with `properties` and a `parent`. The guide's examples only use `page_id` parents, so a `data_source_id` parent plus `markdown` is allowed by the schema but not shown. [official schema; combination unverified]
- Syntax: `> quote`, `![caption](url)`, `<bookmark source="URL" />`, `<embed source="URL" />`, `<callout>...</callout>`.
- `markdown_version`: `v1` (default today, deprecated) and `v2` (Notion-flavored Markdown, recommended, default in the next version; `v1` will then return 400). Send `"markdown_version": "v2"` explicitly.
- `allow_async: true` returns 202 + an async task for large bodies.

**Recommendation:** blocks for bookmark rows (precise, well documented, easy to unit-test). Markdown (v2) for the weekly digest page, which is long prose with headings and lists, created as a child page of the shared parent page.

### 7. Python: notion-client or httpx

- `notion-client` (community port by ramnes of the official JS SDK, not published by Notion) is maintained: 3.1.0 released 2026-05-12, 3.0.0 2026-02-16; Python >= 3.8; built on httpx (>= 0.23); sync `Client` and `AsyncClient`. [secondary] https://pypi.org/pypi/notion-client/json, https://github.com/ramnes/notion-sdk-py
- On `main` it exposes `data_sources`, `views`, `file_uploads`, `async_tasks`, `pages`, `blocks`, `search`; it retries 429 using `Retry-After` with exponential backoff and jitter. **Default `notion_version` is still `"2025-09-03"`**, so pass `notion_version="2026-03-11"` (needed for `/v1/views`). [secondary] https://raw.githubusercontent.com/ramnes/notion-sdk-py/main/notion_client/client.py. Whether 3.1.0 on PyPI already contains `views` was not checked; verify after install.
- Only the JavaScript SDK `@notionhq/client` is official. [official] changelog

**Recommendation:** a thin wrapper on plain `httpx` (about 6 endpoints: create database, retrieve data source, create view, query data source, create page, update page) with our own limiter and Retry-After loop. It removes the dependency-version question and keeps payloads explicit for tests. Using `notion-client` is also acceptable if pinned (`notion-client>=3.1,<4`) with `notion_version="2026-03-11"`.

---

## Google Docs

### 8. Writing a Google Doc

**Option 1: Docs API `documents.create` + `documents.batchUpdate`** [official]
- Available requests include `insertText`, `updateParagraphStyle` (`namedStyleType: HEADING_1..6`), `updateTextStyle` (`textStyle.link.url`, with a `fields` mask such as `"link"`), `createParagraphBullets`, `insertInlineImage`, `insertTable`, `insertRichLink`, `addDocumentTab`; there is **no Markdown/HTML insert request**. https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request
- Index pitfalls:
  - Indices are UTF-16 code units; the body starts at index 1. Emoji and many non-BMP characters count as 2. [unverified, standard Docs API behaviour]
  - Order requests in **descending index order** inside one batchUpdate so earlier inserts do not shift later ones; or insert everything as one text block first and then style ranges computed from it. [official] https://developers.google.com/workspace/docs/api/how-tos/best-practices
  - Text must be inserted inside an existing paragraph; inserting `\n` creates a paragraph; inserted text inherits the style of the text before it (so a heading style leaks into the next line unless reset). `endOfSegmentLocation` appends at the end of the body. [official] request reference
  - `createParagraphBullets` determines nesting from leading tabs **and removes those tabs, shifting later indices**. Presets e.g. `BULLET_DISC_CIRCLE_SQUARE`, `BULLET_ARROW_DIAMOND_DISC`, `NUMBERED_DECIMAL_ALPHA_ROMAN`. [official] https://developers.google.com/workspace/docs/api/how-tos/lists
  - Use `requiredRevisionId` from a fresh `documents.get` when editing an existing doc, to fail instead of corrupting concurrent edits. [official] best-practices
  - Without a `tabId`, requests go to the first tab. [official] best-practices
  - `insertInlineImage` needs a public URL (max 2 kB), PNG/JPEG/GIF, under 50 MB and 25 MP; the image is copied at insert time. [official] request reference

**Option 2 (recommended): Drive API upload with conversion.** Create the file with `files.create`, multipart upload, metadata `{"name": "...", "mimeType": "application/vnd.google-apps.document"}` and media `text/html`. Drive converts on upload. The official import table lists **HTML, plain text, RTF, Word, ODT and Markdown** as sources that convert to Docs; check `about.get(fields="importFormats")` at runtime. [official] https://developers.google.com/workspace/drive/api/guides/manage-uploads
- Multipart is fine up to 5 MB; the digest and even a few hundred bookmarks are far below that. [official] same page
- Markdown: import (Drive "Open in Google Docs", Docs File > Open) and export (`text/markdown`) are now official. [official] https://developers.google.com/workspace/drive/api/guides/ref-export-formats; import listed in manage-uploads. How faithfully the Drive API import renders nested lists, tables and links from Markdown was not tested. [unverified]
- Updating an existing doc by re-uploading content: `files.update` with new media on the Doc's id is reported to replace content while keeping the id and sharing. [secondary/unverified, community posts] Test it on day 1; fallback is "new doc each run, trash the old one" or Docs API `replaceAllText`/delete-and-insert.

**Scope (least privilege):** `https://www.googleapis.com/auth/drive.file` only. It is **non-sensitive**, is listed by the Docs API as the recommended scope, and covers files the app created (both Drive uploads and Docs API edits of those files). `documents` is **sensitive**, `drive` is **restricted**. [official] https://developers.google.com/workspace/docs/api/auth, https://developers.google.com/workspace/drive/api/guides/api-specific-auth

**OAuth for an installed app** [official] https://developers.google.com/identity/protocols/oauth2/native-app
- OAuth client type **Desktop app**; **loopback IP redirect** (`http://127.0.0.1:<random port>`) is the recommended method. Custom URI schemes and the OOB copy/paste flow are no longer supported. Use **PKCE**. Desktop client secrets are not confidential.
- Python: `google-auth-oauthlib` `InstalledAppFlow.from_client_secrets_file(...).run_local_server(port=0)` + `google-api-python-client`, as in the official quickstart. [official] https://developers.google.com/workspace/docs/api/quickstart/python. Store the token JSON (with refresh token) in the plugin's data dir, user-only permissions.
- **Refresh tokens expire after 7 days** when the OAuth consent screen is External and in **Testing** status (unless only profile/email scopes are requested). Other causes: unused for 6 months, the 100 live refresh tokens per account per client cap, time-based access. [official] https://developers.google.com/identity/protocols/oauth2
- **Verification:** apps using only non-sensitive scopes do not have to complete verification; personal-use apps (fewer than 100 users) can click through the "unverified app" screen; the 100-user cap applies in testing. [official] https://support.google.com/cloud/answer/13463073, https://support.google.com/cloud/answer/13464323
- Consequence: each user creates their own Google Cloud project + Desktop OAuth client (bring-your-own client, like rclone), requests only `drive.file`, and **sets the consent screen to "In production"** so the refresh token does not die after 7 days. With only a non-sensitive scope, no verification is needed. [official rules; the combined conclusion is my reading, unverified in practice]
- Shipping a shared client id in the plugin is possible (desktop secrets are not secret) but puts all users on one project's quotas and brand. Not recommended for v1.

**Quotas** [official] https://developers.google.com/workspace/docs/api/limits: Docs API reads 3000/min/project, 300/min/user; writes 600/min/project, **60/min/user**. On 429 use truncated exponential backoff with up to 1 s jitter, max 32 to 64 s. Drive uploads are a single request per doc, so quotas are irrelevant at our volume.

**Recommendation (simplest robust):**
1. Render the export and the weekly digest to **HTML** with one shared template (the same renderer as the local HTML file, minus scripts and CSS that Docs ignores; keep `<h1>/<h2>`, `<ul><li>`, `<a href>`, `<blockquote>`, `<p>`).
2. Upload with Drive `files.create` + conversion, scope `drive.file`, Desktop OAuth with loopback, consent screen "In production".
3. Remember the file id; for the running bookmarks doc, try `files.update` with new media (verify), else create a new doc per run. The weekly digest is a new doc per week, named e.g. `X bookmarks digest 2026-W45`.
4. Use the Docs API batchUpdate only if we later need surgical edits. HTML is preferred over Markdown because HTML conversion has been supported for years and gives exact control of links and headings; Markdown import is official but newer and untested here.

### 9. Google Sheets (brief)

A sortable/filterable table: one row per bookmark, `spreadsheets.values.append` / `batchUpdate`, upsert by looking up the Tweet ID column. Same `drive.file` scope works for sheets the app creates. Quota 300 read and 300 write requests/min/project, 60/min/user. [official] https://developers.google.com/workspace/sheets/api/limits. Could also be produced with one Drive upload of a CSV converted to `application/vnd.google-apps.spreadsheet` (the official manage-uploads example is exactly CSV to Sheets). Good optional "table" target later; not needed for v1.

---

## Local document

### 10. Finding the real Desktop folder

- **Windows:** the Desktop may be redirected (OneDrive Known Folder Move, group policy). The right source is the Known Folder API: `SHGetKnownFolderPath(FOLDERID_Desktop)`, GUID `{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}`, default `%USERPROFILE%\Desktop`. [official] https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid. Fallback: registry `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders`, value `Desktop`, type REG_EXPAND_SZ, so pass it through `os.path.expandvars`. [verified locally: returns `%USERPROFILE%\Desktop`, type 2] Do not use the legacy `Shell Folders` key. [unverified]
- On this machine both methods return the user's own `Desktop` folder (no OneDrive redirection here), so the redirected case is untested. [verified locally]
- `platformdirs.user_desktop_dir()` on Windows calls `SHGetKnownFolderPath` with the same GUID via ctypes, falling back to the registry. [secondary] https://platformdirs.readthedocs.io/en/latest/_modules/platformdirs/windows.html. Usable if we already depend on platformdirs; otherwise 25 lines of ctypes.
- **macOS:** `~/Desktop` (with iCloud "Desktop & Documents" on, the path stays `~/Desktop`). [unverified]
- **Linux:** `xdg-user-dir DESKTOP` if installed; otherwise parse `${XDG_CONFIG_HOME:-~/.config}/user-dirs.dirs` for `XDG_DESKTOP_DIR="$HOME/Desktop"` (values are `$HOME/...` or absolute). [secondary] https://man.archlinux.org/man/user-dirs.dirs.5. If the directory is missing (headless servers), fall back to `~/Desktop` if it exists, else the home directory, and say so in the tool result.
- Always allow a config override (`output_dir`).

Minimal stdlib implementation (no extra deps):

```python
import os, sys, subprocess, re
from pathlib import Path

def desktop_dir() -> Path:
    if override := os.environ.get("X_BOOKMARKS_OUTPUT_DIR"):
        return Path(override).expanduser()
    if sys.platform == "win32":
        try:
            import ctypes, uuid
            from ctypes import wintypes
            class GUID(ctypes.Structure):
                _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD),
                            ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]
            u = uuid.UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")
            g = GUID(u.fields[0], u.fields[1], u.fields[2],
                     (ctypes.c_ubyte * 8)(*u.bytes[8:]))
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
                try:
                    return Path(p.value)
                finally:
                    ctypes.windll.ole32.CoTaskMemFree(p)
        except Exception:
            pass
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                return Path(os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0]))
        except OSError:
            pass
    elif sys.platform.startswith("linux"):
        try:
            out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=3).stdout.strip()
            if out and Path(out).is_dir():
                return Path(out)
        except (OSError, subprocess.SubprocessError):
            pass
        cfg = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "user-dirs.dirs"
        if cfg.is_file():
            m = re.search(r'^XDG_DESKTOP_DIR="([^"]+)"', cfg.read_text(encoding="utf-8"), re.M)
            if m:
                return Path(m.group(1).replace("$HOME", str(Path.home())))
    d = Path.home() / "Desktop"
    return d if d.is_dir() else Path.home()
```

(The Windows ctypes part mirrors what I ran locally today; the Linux part is untested.) Write files atomically: write `name.tmp` in the same folder, then `os.replace`. Write text as UTF-8 explicitly.

### 11. Format recommendation

| Format | Pros | Cons |
|---|---|---|
| Markdown, one file | readable anywhere, diffable, Obsidian/VS Code friendly, easy to test | no filtering or board; long lists get unwieldy |
| Single self-contained HTML | double-click opens in a browser; can embed data as JSON and render a filterable kanban (columns by Status or Type, chips by Category/Tags, search box) with inline JS/CSS, no network | not editable as notes; status changes made there would not sync back (keep it read-only) |
| Obsidian vault mode (one note per bookmark with YAML front matter) | works with Dataview/Bases, backlinks, user can edit status in front matter | many files; only for Obsidian users; must never overwrite user-edited notes |

**Recommendation: both by default, in one folder on the Desktop**, e.g. `Desktop/X Bookmarks/`:
- `x-bookmarks.html`: the browsable board (self-contained, data inlined, works offline, no external scripts or fonts; respects `prefers-color-scheme`).
- `x-bookmarks.md`: the same content grouped by Category, then Type, each item with link, author, date, summary, tags.
- `digest-2026-W45.md` (+ the same digest inside the HTML as a tab).
- Optional `obsidian_vault_path` setting: write `<vault>/X Bookmarks/<tweet-id>.md` per bookmark with front matter (`tweet_id`, `url`, `author`, `posted`, `category`, `tags` as a YAML list, `type`, `status`, `summary`). Only create missing notes and update the plugin-owned keys; leave the body and `status` alone once the file exists.

The plugin's source of truth should be its own state store (JSON or SQLite in the Hermes data dir), not any of the exported files; all three destinations are renders of it.

---

## Prior art

- **xdevplatform/bookmarks-to-notion** (X Developer Platform sample, Python/Flask, Apache-2.0, last pushed 2022). Exports bookmarks "to a Notion page" using X OAuth and Notion public OAuth (client id/secret, redirect URIs in `config.cfg`). Shows the official X bookmarks flow but predates data sources; no database schema documented. [secondary] https://github.com/xdevplatform/bookmarks-to-notion, https://repos.ecosyste.ms/hosts/GitHub/repositories/xdevplatform%2Fbookmarks-to-notion
- **pbadeer/bookmarks-to-notion**: same idea, derived from the sample. [secondary] https://github.com/pbadeer/bookmarks-to-notion
- **X2Notion** (Chrome extension, repo tianzhipeng-git/x2notion): user-made database with **Name, URL, Sender, PostDate, SaveDate**; asks for Notion API key + database id. [secondary] https://chromewebstore.google.com/detail/x2notion/mlkkbdehnmlbliikchgikoaklhednpfh
- **TweetKB** (AdityaVG13/TweetKB): closest to our idea. Local SQLite, **dedupe by X status id** (re-seen bookmarks update the row), stage hashes to skip unchanged items, LLM analysis with **category slugs (`ai-agents`, `coding`, `models`, `tools`, `misc`), entities, tags, summary, "why it matters", embedding**, review state (approve, exclude, tag, needs-review), exports to Obsidian, Markdown, JSONL, CSV and a static interactive `index.html`. Collects via a logged-in browser (scraping), not the API. [secondary] https://github.com/AdityaVG13/TweetKB
- **x2o** (kiki123124/x2o): exports, AI-classifies and builds an Obsidian vault; supports host-model, Gemini or Ollama. [secondary] https://skills.sh/kiki123124
- **Obsidian "X Bookmarks to Vault" plugin**: one note per bookmark, optional local-AI monthly summaries; cookie-based. [secondary] https://community.obsidian.md/plugins/x-bookmarks-to-vault

Lessons: key everything by tweet id; hash the input so re-runs skip unchanged items and do not re-spend LLM tokens; keep a small fixed category list (TweetKB's slugs are close to ours); separate the plugin-owned fields from user-owned fields (status, notes); a static HTML board is a proven local output.

---

## Recommended data model for the Notion database

One database "X Bookmarks" under the shared page, one data source. Plugin-owned properties are overwritten on re-sync; user-owned ones are set once.

| Property | Type | Owner | Notes |
|---|---|---|---|
| Name | title | plugin | LLM one-line summary (fallback: first 80 chars of the tweet) |
| Tweet ID | rich_text | plugin | **upsert key**; string, never number |
| URL | url | plugin | canonical `https://x.com/<handle>/status/<id>` |
| Author | rich_text | plugin | `@handle` (display name in the body) |
| Category | select | plugin | small fixed list from config (e.g. Agents, Coding, Models, Tools, Crypto, Design, Business, Other); no commas in names |
| Tags | multi_select | plugin | lower-case, max ~5 per item; normalise to an existing vocabulary to stop option sprawl (100 per request) |
| Type | select | plugin | Read, Try, Post idea, Reference |
| Status | status | user (set on create only) | Inbox (To-do), In progress (In progress), Done (Complete), Archived (Complete) |
| Summary | rich_text | plugin | 1 to 2 sentences, under 2000 chars |
| Posted | date | plugin | tweet `created_at` |
| Saved | date | plugin | first time the plugin saw the bookmark (X does not return the bookmark time) |
| Link | url | plugin | first outbound link in the tweet, if any |
| Thread | checkbox | plugin | part of a thread / long post |
| Week | rich_text | plugin | ISO week of Saved, e.g. `2026-W45`, used by the digest and as a quick filter |
| Media | files | plugin, optional | external image URLs from the tweet |

Page body (blocks): callout with the summary; quote with the full tweet text (chunked at 2000 chars); bookmark block with the tweet URL; images as external image blocks; a "Why saved / post idea" paragraph for Type = Post idea.

Views to create via `POST /v1/views` (version `2026-03-11`): **Board** grouped by Status (by option), **By category** board grouped by Category, and rename the auto-created "Default view" to **All** (table, sort Posted descending). Weekly digest: a child page of the parent page, written with `markdown` (`markdown_version: "v2"`).

---

## Open questions

1. Notion version conflict: the create-view reference allows only `2026-03-11`, the views guide says `2025-09-03` or later. Plan: send `2026-03-11` everywhere; confirm on the first live call.
2. Does `POST /v1/pages` accept `markdown` together with a `data_source_id` parent? Schema says yes, docs show no example. Only matters if we switch rows to Markdown bodies.
3. Does an `embed` block with an `x.com/.../status/...` URL render the tweet when created via the API? Test once; default to `bookmark`.
4. Does `notion-client` 3.1.0 on PyPI already include `views`, or only `main`? Only relevant if we use the SDK instead of httpx.
5. Which plan is the user's Notion workspace on (180 vs 600 requests/min)? Affects first-sync speed only.
6. Internal connection vs PAT: an internal connection needs the user to be workspace owner (true for a personal workspace). Confirm the user is fine sharing one parent page.
7. Google: does `files.update` with new HTML media on an existing Google Doc replace its content cleanly (keeping id and sharing)? Test on day 1.
8. Google: confirm in practice that a BYO Desktop client with only `drive.file`, consent screen "In production", shows no 7-day expiry and no blocking verification screen.
9. Markdown vs HTML import into Docs: compare fidelity once (nested lists, links, blockquote); HTML is the planned default.
10. OneDrive-redirected Desktop is untested (this machine is not redirected); test on a redirected profile or trust the Known Folder API.
11. Do we want the local HTML board to be read-only (recommended), or allow status edits that the plugin reads back? The latter needs a write path and is out of scope for v1.
12. Category list: fixed in config, or LLM-proposed and then frozen after the first run? Affects select-option sprawl in Notion.
13. Where Hermes stores secrets for plugins (Notion token, Google token JSON); must not be in the repo or the exported files.
