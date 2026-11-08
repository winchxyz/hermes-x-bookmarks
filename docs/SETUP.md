# Owner setup checklist (before or at the start of day 1)

Only the owner can do these steps (accounts, billing, sign-ins). About 20 minutes.

## 1. X developer app (required)

1. Sign in at https://console.x.com with the X account whose bookmarks we read. That same account
   must own the app, or the cheap "owned reads" price ($0.001/post) does not apply.
2. Use a new app for this use case (the existing Sweep app has a different use case on file, and
   its sign-in tokens have an open 401 problem). Use case text, which X treats as binding:
   > Personal tool. Reads my own bookmarks (read-only). Sends post text to an AI model to
   > classify and summarise them. Keeps private copies in my own Notion, Google Docs and local
   > files, and removes copies of posts deleted on X. No posting, no redistribution, no model
   > training.
3. Move the app to the **Pay-per-use** package, **Production** environment.
4. Billing: add a card, buy a small amount of credit, set a **spending limit** (e.g. $5),
   auto-recharge off. A full first sync of up to ~800 bookmarks should cost about $1-3.
5. Keys & Tokens -> User authentication settings -> Set up:
   - Type of App: **Native App** (public client, no secret)
   - Callback URIs (up to 10, exact match): `http://127.0.0.1:8766/callback`,
     `http://127.0.0.1/callback`
   - Website URL: https://github.com/winchxyz
   - App permissions: Read
6. Copy the **OAuth 2.0 Client ID** (shown once; a UI bug may label it "Client Secret").
   Keep it in a password manager; do not paste it in chat. It goes into Hermes as
   `XBM_X_CLIENT_ID` through Hermes' own settings.
7. Bookmark a few test posts on X: one X Article, one normal post whose card is an Article,
   one post quoting an Article, one long post, one thread, one post with images and a link.

## 2. Notion (for the Notion export)

1. https://www.notion.so/profile/integrations -> New internal integration ("X Bookmarks"),
   capabilities Read, Update, Insert content.
2. Create a page "X Bookmarks", open ... -> Connections -> add the integration.
3. Keep the integration token for Hermes settings (`XBM_NOTION_TOKEN`) and copy the page URL.

## 3. Google (for the Google Docs export; can wait for day 3)

1. https://console.cloud.google.com -> new project -> enable **Google Drive API**.
2. OAuth consent screen: External, add yourself as user, then **Publish app** ("In production"),
   otherwise refresh tokens expire after 7 days. Scope `drive.file` needs no verification.
3. Credentials -> OAuth client ID -> **Desktop app**. Keep client ID and secret for Hermes
   (`XBM_GOOGLE_CLIENT_ID`, `XBM_GOOGLE_CLIENT_SECRET`).

## 4. Hermes

Hermes v0.23.0 or newer with a working model (classification runs on your own model; a cheap model
can be set for it later).
