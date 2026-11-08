# X API research for the x-bookmarks Hermes plugin

Research date: 2026-11-07. Scope: pull the user's own X bookmarks (including X Articles), add context (threads, quotes, media, links), sort with an LLM, export to Notion / Google Docs / a local document.

## How to read this document

Every fact carries a confidence tag and a source:

- **[DOC]** confirmed in official docs (docs.x.com) or the official OpenAPI spec (`https://api.x.com/2/openapi.json`, spec `info.version` 2.174, downloaded 2026-11-07).
- **[STAFF]** stated by X staff (user `taycaldwell`, title "X Staff", or the staff automation account `twin`) on the X Developer Community forum (devcommunity.x.com). Official, but not in the docs.
- **[SEC]** secondary: community code, other developers' forum reports, third-party blogs.
- **[UNV]** unverified: inference, or sources that contradict each other. Test it before relying on it.

Main sources (cited by short name below):

| Short name | URL |
| --- | --- |
| pricing | https://docs.x.com/x-api/getting-started/pricing.md |
| rate-limits | https://docs.x.com/x-api/fundamentals/rate-limits.md |
| openapi | https://api.x.com/2/openapi.json |
| get-bookmarks | https://docs.x.com/x-api/users/get-bookmarks.md |
| bm-intro | https://docs.x.com/x-api/posts/bookmarks/introduction.md |
| bm-quickstart | https://docs.x.com/x-api/posts/bookmarks/quickstart/bookmarks-lookup.md |
| data-dict | https://docs.x.com/x-api/fundamentals/data-dictionary.md |
| oauth2-code | https://docs.x.com/resources/fundamentals/authentication/oauth-2-0/authorization-code.md |
| oauth2-token | https://docs.x.com/resources/fundamentals/authentication/oauth-2-0/user-access-token.md |
| dev-apps | https://docs.x.com/fundamentals/developer-apps.md |
| search-intro | https://docs.x.com/x-api/posts/search/introduction.md |
| conv-id | https://docs.x.com/x-api/fundamentals/conversation-id.md |
| articles-intro | https://docs.x.com/x-api/articles/introduction.md |
| policy | https://docs.x.com/developer-terms/policy.md |
| agreement | https://docs.x.com/developer-terms/agreement.md (Last Updated: April 27, 2026) |
| restricted | https://docs.x.com/developer-terms/more-on-restricted-use-cases.md |
| compliance | https://docs.x.com/x-api/compliance/batch-compliance/introduction.md |

Forum threads are cited as `forum/<topic id>`, meaning `https://devcommunity.x.com/t/<topic id>`.

### Spec naming drift: read this first

The OpenAPI spec 2.174 renamed the Post parameters: `post.fields` (not `tweet.fields`), `note_post` (not `note_tweet`), `referenced_posts` (not `referenced_tweets`), `edit_history_post_ids`, and the expansion `referenced_posts` (not `referenced_tweets.id`). [DOC, openapi; get-bookmarks also renders `post.fields`]

But the data dictionary, the bookmarks quickstart, X staff answers from September to November 2026, the official xurl CLI, and all the community code use the old names (`tweet.fields`, `note_tweet`, `referenced_tweets.id`, `article.cover_media`). [DOC data-dict, bm-quickstart; STAFF forum/275354, forum/277915; SEC] A developer asked on 2026-10-29 which names to use, and nobody had answered yet. [forum/279628]

**Plan:** use the old names (`tweet.fields=...&expansions=referenced_tweets.id,...`). Staff confirm they work today. Write one smoke test that checks which names the live API accepts. [UNV: whether `post.fields` works live]

---

## 1. GET /2/users/:id/bookmarks

### Auth

- Security in the spec: `OAuth2UserToken` with scopes `bookmark.read`, `users.read`, `tweet.read`, **or** `UserToken` (OAuth 1.0a user context). There is **no** `BearerToken` entry, so an app-only bearer token cannot call it. [DOC, openapi `getUsersBookmarks`]
- By contrast, `GET /2/tweets`, `GET /2/tweets/:id`, `search/recent` and `search/all` all accept `BearerToken`. `GET /2/users/me` accepts user tokens only. [DOC, openapi]
- Scopes the quickstart lists for OAuth 2.0 PKCE: `bookmark.read` ("Read bookmarks"), `tweet.read`, `users.read` ("for expansions"). [DOC, bm-quickstart]
- `offline.access` is not needed for the call itself. It is needed to get a refresh token. Without it the user has to log in again every 2 hours. [DOC, oauth2-code]
- **Minimal scope set for the plugin:** `tweet.read users.read bookmark.read offline.access`. Add `bookmark.write` only if we create folders or move posts into them (section 3).
- `{id}` must be the authenticated user's numeric id. Get it once from `GET /2/users/me` (75 requests per 15 min per user) and cache it. [DOC, bm-quickstart, rate-limits]

### Parameters and response

- `max_results`: integer, minimum 1, maximum 100. The spec gives no default. [DOC, openapi]
- `pagination_token`: string ("A base32hex-encoded pagination token"). The response `meta` has `result_count`, `next_token`, `previous_token`. Keep requesting while `meta.next_token` is present. [DOC, openapi, get-bookmarks]
- Field selectors: `tweet.fields` (spec: `post.fields`), `expansions`, `user.fields`, `media.fields`, `poll.fields`, `place.fields`. The field enum includes `article`, `article_title`, `note_post`/`note_tweet`, `conversation_id`, `entities`, `attachments`, `card_uri`, `created_at`, `lang`, `public_metrics`, `media_metadata`. The expansions enum includes `article.cover_media`, `article.media_entities`, `attachments.media_keys`, `attachments.media_source_tweet`, `author_id`, `referenced_posts`/`referenced_tweets.id`, `in_reply_to_user_id`. [DOC, openapi `PostFieldsParameter`, `PostExpansionsParameter`]
- There are **no** time filters (`start_time`, `since_id`): the endpoint has only `id`, `max_results`, `pagination_token` and the field selectors. [DOC, openapi] X staff took a request for time filters as feedback only. [STAFF, forum/259589]
- **The time a post was bookmarked is not returned.** Only the post's own `created_at` is. [SEC, forum/259589; DOC: no such field in the `Post` schema]

### How many bookmarks can we reach?

- Legacy docs: "you will get back 800 of your most recent Bookmarked Posts". [SEC, legacy page https://developer.x.com/en/docs/x-api/tweets/bookmarks, seen through a search snippet. The current docs.x.com pages no longer give a number.]
- 2022: removing recent bookmarks makes older ones reachable, so the 800 is a sliding window. [SEC, forum/169433, non-staff Developer Advocate]
- 2026-02: pagination "stops after 2-3 pages" with no `next_token`. Staff: "We're looking into this bug. As a workaround, reduce the number of max_results". The reporter says `max_results=90` worked. [STAFF, forum/257339]
- 2026-08-26: a reproducible stop at 100 + 99 = 199 posts. Folder lookups still returned older ids that were missing from that list. Staff: "I'll check whether the top-level endpoint is windowed. Folder-scoped bookmark lookups are the workaround for older items in the meantime." Nothing resolved since. [STAFF, forum/274280]
- **Conclusion:** plan for a ceiling somewhere between about 200 and 800 most recent bookmarks. The cause is unclear (window or bug). Use `max_results=90` as the default and record how many posts each full run returns. [UNV]

### Ordering

- Not documented. [DOC: neither get-bookmarks nor bm-quickstart mention order]
- In practice it is newest bookmark first. Community sync code relies on that and stops at the first id it has already seen ("incremental cutoff"). [SEC, github.com/sebastienb/xbkmrk `poller/src/sync.ts`]
- Treat this as [UNV]: our incremental sync should tolerate the order being wrong. For example, keep paging until N known ids in a row have been seen, and run a full re-sync from time to time.

### App-only bearer

Not allowed: no `BearerToken` in the spec's security for this operation. [DOC, openapi] Expect a 403 "Unsupported Authentication" error. [UNV: exact error text]

---

## 2. Pricing (pay-per-use) and rate limits

### Is reading your own bookmarks free?

**No. It is discounted, not free.** [DOC, pricing]

- "Owned Reads are requests made by your own developer app for your own data". These endpoints are "priced at **$0.001 per resource** (1,000 resources for $1)". The condition: "when `{id}` matches the authenticated user and that user is the owner of the developer app". `GET /2/users/{id}/bookmarks` ("Your bookmarks") is on the owned-read list. [DOC, pricing]
- `GET /2/users/{id}/bookmarks/folders` and `/folders/{folder_id}` are **not** on the owned-read list. Their billing is undocumented. [DOC, pricing; UNV billing]
- **The user must own the developer app.** If someone else authorizes our app through OAuth to read their own bookmarks, they pay standard rates: $0.005 per post, plus expansions at their own rates. Staff: "The wording in 275286 was looser than it should have been." [STAFF, forum/279443, 2026-10-28]
- The user's idea of "about 1000 per window" probably mixes up the price ("1,000 resources for $1") with a rate limit. The real limit is 180 requests per 15 min (below).

### Standard read rates (per resource returned) [DOC, pricing]

| Resource | Price |
| --- | --- |
| Post | $0.005 |
| User | $0.010 |
| Owned read (bookmarks, own timeline, likes, ...) | $0.001 |
| Media, poll, place returned through expansions (from 2026-11-22) | $0.005 each [STAFF, forum/279443; pricing page rows "being added"] |
| Bookmark create (write), per request | $0.005 |
| Bookmark delete: "Interaction delete" $0.010 per request [UNV: that this row covers bookmark delete] | |

### Billing changes and rules

- **Expansions become billable on 2026-11-22.** "From November 22nd, objects returned through expansions will be billed at the standard PPU rate for that resource ... post, user, media, poll and place expansions." Rates: Post $0.005, User $0.010, Media/Poll/Place $0.005. [STAFF, forum/279110, official announcement of 2026-10-23]
- On owned-read endpoints, expanded objects "inherit the owned-read rate and bill at $0.001 each". Staff named `/tweets`, `/mentions` and `/liked_tweets` explicitly. [STAFF, forum/279443] Bookmarks probably works the same way. [UNV]
- Each media object counts separately: a post with 4 images = 4 media resources. [STAFF, forum/279443]
- **Deduplication:** "Resources are deduplicated within a 24-hour UTC window ... The window resets at midnight UTC. This is a soft guarantee." [DOC, pricing] This covers users, media, polls and places in `includes`, not only posts. [STAFF, forum/279443]
- **Monthly cap:** "Pay-per-usage plans are capped at **3 million Post reads per monthly billing cycle**." [DOC, pricing]
- **Spending limit:** you can set a maximum spend per billing cycle. When it is reached, requests are blocked until the next cycle. A negative balance also blocks requests. [DOC, pricing]
- **Free credits:** "$20 in free X API credits when you save your first eligible payment card", plus a match of the first auto-recharge up to $50. There is no free tier. [DOC, pricing] Minimum credit purchase: $5. [SEC, Hermes xurl SKILL.md troubleshooting table]

### Cost examples (owned app, after 2026-11-22)

- Full bookmark sync of 800 posts with author + media expansions: about 800 x $0.001 + authors and media at $0.001 each, so roughly $1-2. [UNV estimate]
- Each extra `GET /2/tweets` lookup (article body, quoted post, parent post): **$0.005 per post**. It is not an owned read even if the post is ours. [DOC, pricing; STAFF, forum/275286]
- Thread context through search: $0.005 per post returned.

### Rate limits [DOC, rate-limits]

Per-user limits apply to OAuth user tokens. Per-app limits apply to app-only bearer tokens. All windows are 15 minutes unless noted. Exceeding a limit returns HTTP 429. Read the headers `x-rate-limit-limit`, `x-rate-limit-remaining`, `x-rate-limit-reset`.

| Endpoint | Per app | Per user |
| --- | --- | --- |
| GET /2/users/:id/bookmarks | — | **180 / 15 min** |
| GET /2/users/:id/bookmarks/folders | 50 / 15 min | 50 / 15 min |
| GET /2/users/:id/bookmarks/folders/:folder_id | 50 / 15 min | 50 / 15 min |
| POST /2/users/:id/bookmarks | — | 50 / 15 min |
| DELETE /2/users/:id/bookmarks/:tweet_id | — | 50 / 15 min |
| GET /2/tweets (up to 100 ids per call) | 3,500 / 15 min | 5,000 / 15 min |
| GET /2/tweets/:id | 450 / 15 min | 900 / 15 min |
| GET /2/users/me | — | 75 / 15 min |
| GET /2/tweets/search/recent | 450 / 15 min | 300 / 15 min (10 results by default, max 100; query up to 512 chars) |
| GET /2/tweets/search/all | 1 / s and 300 / 15 min | 1 / s (max 500 results; query up to 1024 chars) |

- The rate-limit page lists no 24-hour limit for these endpoints, and no monthly request cap. The only monthly cap is the 3M Post reads billing cap. [DOC, rate-limits, pricing]
- `GET /2/tweets` takes `ids` with 1 to 100 items. [DOC, openapi] Always batch: one call for up to 100 posts.

---

## 3. Bookmark folders, adding and removing bookmarks

### Read

- `GET /2/users/:id/bookmarks/folders`: scopes `users.read`, `bookmark.read`; accepts `max_results` and `pagination_token`. Returns `data[]` of `{id, name}`. [DOC, openapi `getUsersBookmarkFolders`]
- `GET /2/users/:id/bookmarks/folders/:folder_id`: scopes `bookmark.read`, `users.read`, `tweet.read`. The documented response is `data[]` of `{id}` only ("The Posts in this bookmark folder, by ID"). It has no post fields and no expansions. [DOC, openapi `GetUsersBookmarksByFolderIdResponse`]
- Real behaviour:
  - The folder list returns at most 20 folders, ignores `max_results`, and has no `meta`. [SEC, forum/260102]
  - The folder contents endpoint returns about 20 post ids, gives no `next_token`, and rejects `max_results` and `pagination_token` with HTTP 400 "The query parameter [max_results] is not one of [id,folder_id]". [SEC, forum/258508, forum/267427]
  - Staff on 2026-10-14: "The folder endpoint has historically returned a fixed page of about 20 Post IDs and does not honor max_results ... Folder responses also typically omit pagination metadata ... We'll keep the folder-endpoint pagination gap on the API side of the backlog." [STAFF, forum/278186]
- The main bookmarks list does **not** say which folder a post is in. [SEC, forum/258508, forum/267427]
- Folder access needs X Premium in the app (a product fact). [UNV for the API]
- **Use:** read folder names and up to 20 recent ids per folder. Treat them as hints for the LLM sorting ("user already filed this under X"). Folders cannot be fully mirrored. Hydrate the ids with `GET /2/tweets?ids=` ($0.005 per post).

### Write (new in the spec, verify live)

- `POST /2/users/:id/bookmarks`: scopes `bookmark.write`, `tweet.read`, `users.read`. Body: `tweet_id` **or** `tweet_ids` (1-25), plus an optional `folder_id`: "Optional ID of the Bookmark folder to add the Post(s) to. When omitted, Posts are added to the user's top-level Bookmarks only." "Billing and rate limits still apply per HTTP request." [DOC, openapi `createUsersBookmark`, `CreateUsersBookmarkRequest`]
- `POST /2/users/:id/bookmarks/folders`: scopes `users.read`, `bookmark.write`. Body `{ "name": "<1-25 chars>" }`. Returns `{id, name}`. [DOC, openapi `createUsersBookmarkFolder`]
- `DELETE /2/users/:id/bookmarks/:tweet_id`: scopes `tweet.read`, `users.read`, `bookmark.write`. [DOC, openapi]
- There is **no** documented endpoint to rename or delete a folder, or to remove a post from one folder only. [DOC, openapi: no PUT/PATCH/DELETE on `/bookmarks/folders/*`] Whether re-bookmarking an already-bookmarked post with `folder_id` moves it is not documented. [UNV]
- The bm-intro page still lists only the 5 classic endpoints. The folder create endpoint and `folder_id`/`tweet_ids` appear only in the spec, so they are recent. [DOC, bm-intro vs openapi]

---

## 4. X Articles

### What the docs say

- Data dictionary: `article` "Contains metadata for the Article present in this Tweet" and is used "to get the text and entities of an Article". The docs do not list its sub-fields. [DOC, data-dict]
- In the spec, `article` is `{"type":"object"}` (untyped). `article_title` is "Metadata about the long-form Article attached to this Post, if any." The expansions `article.cover_media` and `article.media_entities` exist. [DOC, openapi `Post`, `PostExpansionsParameter`]
- The Articles API only writes: `POST /2/articles/draft` and `POST /2/articles/{article_id}/publish`. There is **no** read-by-article-id endpoint. [DOC, articles-intro; openapi lists only `/2/articles/draft` and `/2/articles/{article_id}/publish`]
- `note_tweet` (spec name `note_post`) is a separate thing: "The full content of the Post, including text beyond 280 characters". It has `text` and `entities` (hashtags, cashtags, mentions, urls). [DOC, openapi `PostNotePost`; data-dict]

### Staff answer on getting the body (2026-09-08)

"For ID lookup on GET /2/tweets / GET /2/tweets/:id, request both with tweet.fields=note_tweet,article". For long Posts the body is in `note_tweet`. For X Articles it is in `article` ("Article metadata/text/entities on that Tweet. Default text is often just the short/t.co form"). "An Article Tweet is not expected to also fill note_tweet". [STAFF, forum/275354]

### Article object shape (from live payloads, secondary)

```json
"article": {
  "title": "...",
  "preview_text": "first lines ...",
  "plain_text": "full body, paragraphs separated by \n",
  "cover_media": "<media_key>",
  "media_entities": ["<media_key>", "..."],
  "entities": { "hashtags": [...], "mentions": [...], "urls": [...], "...": "..." }
}
```

Sources: [SEC] github.com/colebemis/notion-workers `twitter/src/x.ts` ("Shape verified against live payloads: `plain_text` carries the full body with \n between paragraphs; `cover_media`/`media_entities` are media keys resolved via the article.* expansions into includes.media (no text-position offsets)"). Also 0xNyk/xint `lib/api.ts`, sebastienb/xbkmrk `poller/src/sync.ts` ("cover_media is a bare media_key string (docs show an object — handle both)"), and the Hermes bundled xurl skill ("Request the `article` tweet field and ingest `data.article.plain_text`"; NousResearch/hermes-agent `skills/social-media/xurl/SKILL.md`).

**Answer: yes, the full Article body can be read through the API, but only as plain text.** [STAFF + SEC]

- Rich structure is not exposed: no headings, bold, link anchors, lists, code blocks or media placement. A developer asked for Markdown/HTML; staff said "we'll look into it" (2026-05-26). [STAFF, forum/266691]
- Code blocks come out of `plain_text` in the wrong order, with no position information. [SEC, forum/257791]
- Media in `media_entities` has no position offsets, so images cannot be placed inline. [SEC, colebemis comment]

### Case (a): the bookmarked post is itself an Article

1. In the bookmarks call, request `tweet.fields=...,article,note_tweet,...` and `expansions=...,article.cover_media,article.media_entities` with `media.fields=url,preview_image_url,alt_text,type,width,height,variants`. The spec lists `article` for this endpoint, and community code requests it there. [DOC openapi; SEC colebemis]
2. **Detection:** `article.title` is present (or `article_title`). The top-level `text` is usually only a t.co link. [STAFF forum/275354; SEC xbkmrk, kzinmr]
3. If `article.title` is present but `article.plain_text` is missing, re-fetch with `GET /2/tweets?ids=<id,...>&tweet.fields=article` ($0.005 per post).
   - One community skill reports that asking for `note_tweet` and `article` together "silently drops" `plain_text`. That conflicts with the staff answer and with other community code that combines them. [UNV; SEC github.com/kzinmr/ai-topics-agent `assets/skills/x-article-retrieval/SKILL.md`]
   - The same source says very new articles may lack `plain_text` for a few minutes. [SEC]
4. The cover image is `includes.media` where `media_key == article.cover_media`.

### Case (b): a normal post that points to an Article

- **(b1) It quotes an Article post.** `referenced_tweets` contains `{type: "quoted", id: Q}`. With `expansions=referenced_tweets.id`, the quoted post appears in `includes.tweets` with the requested `tweet.fields`. Check `includes.tweets[Q].article.title`. If the body is missing there, call `GET /2/tweets?ids=Q&tweet.fields=article`. The body lives on the **quoted** post's id, not the outer post's id. [SEC, kzinmr skill "Quoted tweet with X Article chain"; mechanism DOC data-dict/openapi referenced posts] Whether `article.plain_text` is filled for expanded posts in `includes`, or only for primary `data`, is [UNV]. Test it.
- **(b2) It links an Article as a card.** `entities.urls[].expanded_url` / `unwound_url` matches `x.com/i/article/<n>` or `x.com/<user>/article/<n>`.
  - There is no official article-id lookup (see above).
  - Whether `<n>` equals the Article's post id is **contradictory**. One community tool feeds the number from `x.com/<user>/article/<n>` straight into `GET /2/tweets/<n>` [SEC, github.com/freesurf-ecosystem/feedless-digest `scripts/x-article-resolve.mjs`]. Another says "Article ID ≠ Tweet ID — `x.com/i/article/ID` is the article resource, not the tweet" [SEC, kzinmr].
  - **Plan:** try `GET /2/tweets?ids=<n>&tweet.fields=article,author_id`. Accept the result only if it has `article.title`. Otherwise fall back.
- **Fallbacks when the body cannot be fetched** (all through the official API):
  1. The URL entity's preview: `entities.urls[].title`, `.description`, `.images[]` (url/width/height), `.unwound_url`, `.status`. These are in the spec as "A URL entity found in the Post text, enriched with link metadata". [DOC, openapi `PostEntities.urls`]
  2. `card_uri` (field exists; contents undocumented). [DOC openapi; UNV contents]
  3. `search/recent` with `url:"x.com/i/article/<n>"` to find the original Article post. Only covers the last 7 days, and the `url:` operator misses links past about 280 chars in long posts. [UNV for article links; DOC search-intro 7 days; STAFF forum/277915 on the `url:` gap]
  4. Store the link plus the preview, mark it `body_unavailable`, and let the user open it on X.
- Scraping x.com, the internal `x.com/i/api/...` endpoints, or logged-in browser automation are **out of scope**: they break X's rules. Some community code mentions them; we will not use them.

### Long posts (note tweets)

- Request `note_tweet`. Use `note_tweet.text` when present, otherwise `text`. Top-level `text` and `entities` can be truncated to the display text. [STAFF, forum/277915]
- Some long posts use Mathematical Alphanumeric Unicode (U+1D400-U+1D7FF) for bold/italic. Normalise it before the LLM step and before export. [SEC, kzinmr skill]
- Article `plain_text` often contains zero-width characters (U+200B, U+200C, U+200D, U+2060, U+FEFF). Strip them: Hermes' prompt-injection scanner can block a run because of them. [SEC, kzinmr skill, observed in a Hermes setup]

---

## 5. Thread context, quotes, replies, media, links

### Fields to request on every post-returning call

```
tweet.fields=id,text,created_at,author_id,conversation_id,in_reply_to_user_id,referenced_tweets,entities,attachments,lang,public_metrics,note_tweet,article,card_uri
expansions=author_id,attachments.media_keys,referenced_tweets.id,referenced_tweets.id.author_id,article.cover_media,article.media_entities
media.fields=media_key,type,url,preview_image_url,alt_text,width,height,variants,duration_ms
user.fields=id,name,username,profile_image_url,verified
```

[SEC: this is colebemis' bookmark request with media fields added. Field and expansion names: DOC data-dict/openapi. Note that `referenced_tweets.id.author_id` is not in the spec 2.174 enum, but staff threads use it.]

Cost after 2026-11-22: each expanded post, user and media object is billed (owned rate $0.001 on the bookmarks call; $0.005 / $0.010 on `GET /2/tweets` and search). Request only what export needs. [STAFF forum/279110]

### Quoted posts and replied-to posts

- `referenced_tweets[]` holds `{type: retweeted|quoted|replied_to, id}`. The expansion `referenced_tweets.id` puts those posts into `includes.tweets`. [DOC, openapi `PostReferencedPosts`; data-dict]
- Expanded posts are one level deep. The parent of a parent needs another `GET /2/tweets?ids=` call. [UNV, standard v2 behaviour]

### The author's thread around a bookmarked post

- `conversation_id` is "The ID of the conversation this Post belongs to (matches the root Post's ID)". [DOC, openapi `Post`]
- Docs recipe: `GET /2/tweets/search/recent?query=conversation_id:<root_id>`, which "returns all replies to the original post, sorted reverse-chronologically". [DOC, conv-id] Add `from:<author_username>` (or `to:`/`is:reply` as needed) to keep only the author's own thread. [UNV: standard operators, not stated on that page]
- `search/recent` only covers the **last 7 days** ("`start_time` ... Must be within the last 7 days"). [DOC, openapi; search-intro]
- `search/all` (full archive back to March 2006) is "Available to pay-per-use and Enterprise customers". Limits: 1 request/s, 300 per 15 min, up to 500 results per call. [DOC, search-intro, rate-limits] Price: Post reads at $0.005 each. [DOC pricing, by resource type]
- **Cheaper ways to get ancestors:**
  - Walk `referenced_tweets[type=replied_to]` upward in batches with `GET /2/tweets?ids=` (up to 100 ids per call, $0.005 per post). This works at any age.
  - The root post is `GET /2/tweets/<conversation_id>`.
  - Descendants (the rest of the thread below the bookmarked post) need search: `search/recent` if the root is under 7 days old, otherwise `search/all`.
- **Suggested policy:** fetch the root plus the ancestors by default. Fetch the full thread through `search/all` only when the LLM step, or the user, asks for it. Set a per-run budget.

### Media

- `attachments.media_keys` plus `expansions=attachments.media_keys`, then `includes.media[]` with `media_key`, `type` (photo/video/animated_gif), `url` (photos), `preview_image_url` (video/GIF thumbnail), `alt_text` (up to 1000 chars), `variants` (video renditions), `width`, `height`, `duration_ms`. [DOC, data-dict, openapi `MediaFieldsParameter`]
- `attachments.media_source_tweet` expands the post the media originally came from. [DOC, openapi]
- From 2026-11-22 each media object is billed. [STAFF forum/279443]
- Policy: store media **URLs** and alt text, not downloaded copies. Copies would be X Content stored offline, which we would have to keep current and delete. [UNV interpretation of policy]

### External links

`entities.urls[]` gives `url` (t.co), `expanded_url`, `display_url`, `unwound_url` ("final destination after following redirects"), `status` (HTTP status), `title`, `description`, `images[]` (url/width/height), `media_key`. [DOC, openapi `PostEntities`; data-dict sample shows `status`, `title`, `description`, `unwound_url`] For long posts, use `note_tweet.entities.urls` (only has url/expanded_url/display_url). [DOC, openapi `PostNotePost`]

---

## 6. OAuth 2.0 practicalities

### Endpoints [DOC]

- Authorize: `https://x.com/i/oauth2/authorize`. The spec gives `https://api.x.com/2/oauth2/authorize`; the docs use `x.com/i/oauth2/authorize`. [DOC, oauth2-token vs openapi]
- Token: `POST https://api.x.com/2/oauth2/token`, `Content-Type: application/x-www-form-urlencoded`. [DOC, oauth2-token]
- Revoke: `POST https://api.x.com/2/oauth2/revoke` (body `token`, plus `client_id` for public clients). Users can also revoke at x.com/settings/connected_apps. [DOC, oauth2-token]

### Authorize request

- Parameters: `response_type=code`, `client_id`, `redirect_uri`, `scope` (space-separated), `state` (up to 500 chars, check it on return), `code_challenge`, `code_challenge_method` (`S256` or `plain`). Use S256. [DOC, oauth2-code, oauth2-token]
- An empty `state` causes a misleading `invalid_request` error. [SEC, forum/180388]

### Token lifetimes and refresh

- The authorization code is valid for **30 seconds**: exchange it immediately. [DOC, oauth2-code]
- The access token lasts **2 hours** ("will only stay valid for two hours" unless `offline.access` is used). [DOC, oauth2-code] `expires_in` in the token response is the authoritative value. [UNV]
- A refresh token is only issued with `offline.access`. [DOC, oauth2-code]
- **Rotation:** refresh tokens are single-use. "When the token endpoint successfully processes a refresh ... the old refresh token is immediately invalidated server-side and a new one is issued." Staff recommendation: treat a 400/401 "invalid" refresh as dead and re-authorize; retry with backoff only on 5xx; briefly keep the previous token as a fallback. [STAFF, forum/271768]
- Refresh token lifetime: commonly cited as 6 months, or until revoked. [SEC, forum/248555, developer report; not in docs] Users report random `invalid_request` "Value passed for the token was invalid" errors. [SEC, forum/248555, forum/227552]
- **Rules for us:**
  - Persist the new refresh token *before* using the new access token.
  - Never refresh concurrently: one process, plus a file lock.
  - Refresh about 60 s before expiry.

### Public vs confidential client

- "Confidential clients receive a Client Secret. Public clients use PKCE only." Web App and Automated App/Bot are confidential; Native App and Single Page App are public. [DOC, dev-apps]
- Public clients send `client_id` in the request body. Confidential clients send `Authorization: Basic base64(client_id:client_secret)`. [DOC, oauth2-token]
- xurl's code adds that X requires the Basic header for confidential clients, and that auto-detecting the auth style is unreliable ("unauthorized_client: Missing valid authorization header"). So pick the style explicitly. [SEC, github.com/xdevplatform/xurl `auth/auth.go`]
- **Choice for a local plugin:** create the app as **Native App (public client)**. Then no client secret is stored on disk, and the PKCE flow uses `client_id` only.
  - The Hermes xurl skill's troubleshooting table says `unauthorized_client` happens when the app type is "Native App" and suggests switching to Web App. That is xurl-specific, because xurl sends a secret when it has one. [SEC, Hermes xurl SKILL.md]

### Callback URLs

- Exact match "including trailing slashes". "Maximum of **10 callback URLs** per app". Use `https://` in production. For local development use "`http://127.0.0.1` (not `localhost`)". [DOC, dev-apps]
- The docs say nothing about ports. Because matching is exact, register a fixed port, e.g. `http://127.0.0.1:8766/callback`. [UNV for port wildcards: assume none]
- Conflict: xurl's default is `http://localhost:8080/callback`, and the xurl README tells users to register that, so `localhost` apparently works in practice too. [SEC, xurl README] Use `127.0.0.1` as the docs say.
- An unregistered URL returns "Callback URL not approved for this client application". [SEC, search snippet of docs.x.com fundamentals]
- Allow a headless mode (print the authorize URL, paste back the redirect URL or the code), like `xurl auth oauth2 --headless`. Mind the 30 s code lifetime. [SEC, xurl README]

### Creating the app in the Developer Console (console.x.com), 2026 flow

From [DOC, dev-apps; getting-access https://docs.x.com/x-api/getting-started/getting-access.md] plus [SEC, xurl README] for the package step:

1. Sign in at https://console.x.com with the X account whose bookmarks we read. The **same account must own the app**, or owned-read pricing does not apply.
2. Accept the Developer Agreement and Policy and complete the profile ("how you'll use the API").
3. **New App**: name, description, **use case**. The use case is binding (section 8), so state it fully: "personal tool; reads my own bookmarks; sends post text to an LLM (provider X) to classify/summarise; exports private copies to my Notion / Google Docs / local files; keeps them in sync with deletions; no redistribution, no model training."
4. Move the app to the **Pay-per-use** package and the **Production** environment. Without this, reads fail with `client-forbidden` / `client-not-enrolled`. [SEC, xurl README "Apps -> Manage apps -> Move to package -> Pay-per-use -> Production"]
5. Billing: add a card (this unlocks the $20 credit), buy credits, and **set a spending limit**. Leave auto-recharge off at first. [DOC, pricing]
6. Keys & Tokens tab, **User authentication settings -> Set up**:
   - Type of App: **Native App** (public).
   - Callback URI: `http://127.0.0.1:<port>/callback`.
   - Website URL (required field).
   - App permissions: Read (the OAuth 1.0a permission level). Choose "Read and write" only if folder writes are needed; changing it later forces users to re-authorize. [DOC, dev-apps]
7. Copy the **OAuth 2.0 Client ID**. "Credentials are only displayed once." [DOC, getting-access] A known UI bug labels the Client ID as "Client Secret"; the real Client ID ends in `MTpjaQ`. [SEC, Hermes xurl SKILL.md]

Scopes are requested at authorize time, not set in the console: `tweet.read users.read bookmark.read offline.access` (+ `bookmark.write`). [DOC, oauth2-code]

---

## 7. Relying on xurl (Hermes bundled skill) instead of our own OAuth

### Facts

- Hermes ships `skills/social-media/xurl/SKILL.md` (v1.1.3). Its frontmatter says `platforms: [linux, macos]` (not Windows), and its prerequisite is the `xurl` command. [SEC/primary for Hermes, github.com/NousResearch/hermes-agent]
- xurl is the X developer platform's official CLI (github.com/xdevplatform/xurl, latest release v1.3.4, 2026-09-29). It ships Windows x86_64/arm64 zips, and you can install it with npm `@xdevplatform/xurl`. [SEC/primary for xurl, GitHub releases]
- **It does OAuth2 PKCE user login:** `xurl auth apps add <app> --client-id ... --client-secret ...`, then `xurl auth oauth2 --app <app>`. That opens a browser, uses S256, and listens on the redirect URI (default `http://localhost:8080/callback`, listening on both 127.0.0.1 and ::1). There is also a `--headless` flow. Tokens are stored in `~/.xurl/auth.yml` and auto-refresh. [xurl README, `auth/auth.go`]
- **It can read bookmarks:**
  - The shortcut `xurl bookmarks -n N` calls `/2/users/{id}/bookmarks?max_results=N&tweet.fields=created_at,public_metrics,entities&expansions=author_id&user.fields=username,name`. It has no pagination and no article/note_tweet fields. [xurl `api/shortcuts.go`]
  - Raw mode (`xurl '/2/users/<id>/bookmarks?max_results=90&pagination_token=...&tweet.fields=...'`) gives full control. [xurl README]
- `xurl token [--app X] [-u user]` "prints a valid OAuth2 access token ... If the stored token has expired it is refreshed and persisted first. This command never opens a browser, so it is safe to use in scripts". [xurl README] **This is the best integration point:** the plugin calls `xurl token`, then does its own HTTP with that bearer token.
- **Scopes: xurl always requests a fixed, very broad set:** tweet/users/bookmark/follows/list/block/mute/like read, `users.email`, `dm.read`, `broadcast.read`, every matching `.write` scope including `tweet.write` and `dm.write`, plus `offline.access` and `space.read`. They cannot be configured. [xurl `auth/auth.go` `getOAuth2Scopes`]
- The Hermes skill forbids the agent from reading `~/.xurl`, using `--verbose`, or passing secrets inline. The user registers the app and logs in outside the agent session. [Hermes xurl SKILL.md]

### Trade-offs

| | Rely on xurl | Own OAuth in the plugin |
| --- | --- | --- |
| Effort tomorrow | Low: shell out to `xurl token`, handle "not logged in". | Medium: PKCE, loopback listener, token store, locked rotation. |
| Token handling | Done, maintained by X's own team; refresh rotation handled. | We own the rotation bugs (single-use refresh tokens). |
| Scope minimisation | **No**: the token can post, DM and read email. Large blast radius if the agent or a prompt injection misuses it. | Yes: read-only `tweet.read users.read bookmark.read offline.access`. |
| Secrets on disk | Client secret plus tokens in plaintext YAML in `~/.xurl`. | Can use a public client (no secret) and the OS keyring. |
| Windows | Binary exists, but the Hermes skill declares linux/macos only; untested. | Pure Python, works wherever Hermes runs. |
| Coupling | Shared with the user's other xurl use (default app/user confusion is the skill's #1 pitfall). | Independent. |
| Callback | `localhost:8080` by default; must match the console. | `127.0.0.1:<port>`, per the docs. |

**Recommendation:** support both. Default to our own minimal-scope PKCE (public client, keyring storage). Add an optional `auth: xurl` mode that calls `xurl token --app <name>` for users who already set up xurl. Never read `~/.xurl` directly.

---

## 8. Developer Agreement and Policy constraints

### Storing post text locally and in Notion / Google Docs

- "If you store X Content offline, you must keep it up to date with the current state of that content on X". You must delete or modify stored content when it is deleted or modified on X (including made private/protected, suspended, withheld). Do it "as soon as reasonably possible, or within 24 hours of a request from X or the account owner". The policy sets no specific check interval. [DOC, policy; STAFF, forum/278439] Agreement IV.B: "within twenty four (24) hours after a written request to do so by X". [DOC, agreement]
- "keep X Content confidential and secure from unauthorized access". [DOC, agreement III.G]
- Redistribution: you "may only distribute Post IDs, Direct Message IDs, and/or User IDs". Exception: up to 500 public Post/User objects per user per day, by non-automated means such as spreadsheets or PDFs. "Any X Content provided to third parties remains subject to this Policy." [DOC, policy] The agreement forbids to "sell, rent, lease, sublicense, distribute, redistribute, syndicate" X Content. [DOC, agreement III.A(d)]
- Whether writing the user's *own* bookmarks into the user's *own* private Notion/Google workspace counts as "providing to a third party" is not addressed. Reasonable reading: it is the user's own offline storage, but it still has to be kept current and deleted on removal. Never publish or share those pages. [UNV]
- Display integrity: "You must maintain the integrity of all X Content that you display". [DOC, policy] So never present LLM rewrites as the author's words: keep the original text and a link, and label summaries as summaries.
- Protected accounts: "You must respect the protected and blocked status of all X Content." [DOC, policy] Bookmarks can include posts from protected accounts the user follows. Keep them private, and delete them when they become inaccessible.
- Sensitive inferences: "Never derive or infer, or store derived or inferred, information about a X user's" health, political beliefs, sexual orientation, etc. [DOC, restricted] **The LLM sorting prompt must not label authors by sensitive traits.** Categorise the *content topic* only.

### Sending post text to an LLM

- Training is banned: "use the X API or X Content to fine-tune or train a foundation or frontier model" is prohibited (agreement III.A(k)). The restricted-use page says the same, with Grok the only exception. [DOC, agreement, restricted] Use LLM providers and settings that do not train on our inputs.
- Inference through a third-party model is **not explicitly addressed** in the agreement or policy. [DOC, agreement, policy]
- Staff on a personal research tool (2026-10-16): the use case on file covered "no posting, redistribution", but "If you later expand the scope, for example by sending Post text to a third-party model, keeping a raw-text archive, or using the data commercially, let us know and get approval before you make that change, as the Developer Policy requires." So X treats third-party LLM processing as a use case that must be declared and approved. [STAFF, forum/278439]
- "Your use case description is binding on you" and a new purpose needs approval first. [DOC, policy] A direct question about sending posts to ChatGPT was still unanswered on 2026-11-07. [forum/279439]
- **Action:** write the LLM step and the export targets into the app's use-case description from day one (section 6, step 3). If X asks, request confirmation.

### Distributing the plugin

- "You are not permitted to register multiple applications for a single use case". The policy warns that "requiring your end users to register applications for the purpose of using your tool or service" could lead to enforcement. [DOC, restricted]
- Staff (2026-08-18), on a free kit where each user creates their own developer app: "No — distributing a completed kit that other people run by creating their own Developer App isn't permitted ... A write-up of how you built your own personal integration is fine ... If this is a product others use, register one app and have users authorize it with OAuth instead." [STAFF, forum/273564]
- **Conflict for us:** owned-read pricing ($0.001) only applies when the reader owns the app, but a published plugin that tells every user to create their own app is what X says is not permitted. With one shared app, every other user's reads are billed to the app owner at $0.005 per post plus expansions. [STAFF forum/279443]

### Deletion compliance tooling

- Batch compliance: upload Post ids, then get back `delete` (deleted/protected/deactivated/suspended), `rehydrate` (`tweet_edited`), or `scrub_geo`. The endpoints are `/2/compliance/jobs*` with **app-only bearer** auth (the plugin would need the app's bearer token as well). [DOC, compliance; openapi security `BearerToken`] Plan availability and price on pay-per-use are undocumented. [UNV]
- Cheaper fallback: re-hydrate stored ids with `GET /2/tweets?ids=` (100 per call). Ids that come back in `errors` (not found / not authorized) mean delete. But it costs $0.005 per post per check. With 24 h dedup, check at most once a day, and only items exported in the last N months. [DOC pricing, openapi; UNV policy sufficiency]
- Bookmarks that disappear from the bookmarks list (the user un-bookmarked) are not a policy deletion, but the user would probably expect them archived or removed. Make it a setting.

---

## Open questions (test on day 1)

1. Do `tweet.fields` / `note_tweet` / `referenced_tweets.id` (old names) and `post.fields` / `note_post` / `referenced_posts` (spec 2.174) both work on `GET /2/users/:id/bookmarks` today? Which one does the response use?
2. Does the bookmarks endpoint return `article.plain_text` inline? Does it drop `plain_text` when `note_tweet` is also requested? Is `article` filled for posts in `includes.tweets` (quoted Articles)?
3. How many bookmarks does a full traversal return for this account (199? 800?) with `max_results=90` vs 100? Is the order newest-bookmarked-first?
4. Does `GET /2/tweets/<n>` work for `n` taken from `x.com/i/article/<n>` and from `x.com/<user>/article/<n>`?
5. Do the folder endpoints still cap at 20, and are they billed as owned reads? Does `POST /2/users/:id/bookmarks` with `folder_id` move an already-bookmarked post?
6. Does the Developer Console accept a `http://127.0.0.1:<port>/callback` callback for a Native App? Does PKCE token exchange work with `client_id` only (no secret)?
7. Exact billing seen in the Developer Console for one bookmarks page with expansions, after 2026-11-22 (owned rate on `includes`?).
8. Is batch compliance (`/2/compliance/jobs`) available on pay-per-use, and what does it cost?
9. Will X confirm that sending post text to a third-party LLM fits our use case (watch forum/279439)?
10. Distribution model: personal-only plugin (owned app, cheap), or one registered app that others authorize (policy-safe, standard prices billed to the app owner)?

## Design implications

1. **Auth:** our own OAuth 2.0 PKCE, public (Native App) client, scopes `tweet.read users.read bookmark.read offline.access`. Add `bookmark.write` only behind a flag. Loopback `http://127.0.0.1:<fixed port>/callback`, plus a headless paste-the-URL mode. Tokens in the OS keyring. Rotating refresh under a file lock, with the new refresh token persisted first. Optional `xurl token` adapter.
2. **Sync:** page `GET /2/users/:id/bookmarks` with `max_results=90`. Store `next_token` progress and stop on no `next_token`. Treat the result as a window of recent bookmarks, not full history. Record `first_seen_at` ourselves, because X has no bookmark time. Do an incremental cutoff on known ids, plus a periodic full pass.
3. **One rich call, then batched hydration:** request article/note_tweet/entities/referenced posts/media in the bookmarks call (owned rate). Then make **one** `GET /2/tweets?ids=` batch (up to 100) for everything missing: article bodies, quoted Articles, parents, thread roots, and article-link candidates. Cache by post id and respect the 24 h UTC dedup.
4. **Text resolution order:** `article.plain_text` (with `article.title`), then `note_tweet.text`, then `text`. Strip zero-width and math-alphanumeric characters. Mark Articles `format: plain_text_only`.
5. **Article links (case b2):** try `GET /2/tweets/<n>`. If that fails, use the URL-entity preview (`title`, `description`, `images`). Otherwise keep the link only with `body_unavailable`. No scraping, ever.
6. **Threads:** root plus ancestors by default (`GET /2/tweets` batches). Full author thread on demand: `search/recent` for roots under 7 days old, `search/all` (1 req/s) for older ones, with a per-run cost budget.
7. **Cost guard:** estimate the cost before each run (owned $0.001 vs standard $0.005 per post, $0.010 per user, $0.005 per media). Keep expansions to what export uses. Show the user the estimate and the spending limit. Never loop past the 429 headers.
8. **Folders:** read folder names and the about 20 ids per folder as sorting hints. Do not promise folder mirroring. Folder writes (create folder, file post) are optional and need `bookmark.write`.
9. **Compliance:** a daily (at most) re-check of exported items that deletes or updates local, Notion and Google Docs copies when a post is deleted, protected or edited. Keep post ids and links as the primary record. Never publish exports. No model training. LLM prompts classify topics, never infer sensitive traits about authors.
10. **Use-case text and distribution:** register the app's use case to include the LLM step and the private exports. Decide before publishing whether the plugin is a personal integration (each person builds their own, which per staff is a write-up, not a kit) or a product with one app that users authorize.
