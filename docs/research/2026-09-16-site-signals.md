# What a website publishes for machines and AI -- the signals, who honours them, how to detect them

*Research for the Site Report's "What the site declares to machines" section (PR #99),
16 September 2026. Every real-site example below was fetched on that date with the engine's
own User-Agent (`... webgraph/0.1 (+https://github.com/webgraph/webgraph)`), one request a
second; nothing was fetched as another bot. Spec pages were read the same day. Items marked
**[unverified]** could not be confirmed from a primary source within the budget.*

The short version: in 2026 a site can say a great deal to machines, and almost none of it is
enforced. Everything in the *Declarations to AI* group is a preference a crawler chooses to
read; the *Discovery*, *Agents*, *Metadata* and *Trust* groups are conventions that a specific
consumer (a search engine, an agent framework, a social card renderer, a security researcher)
actually acts on. The report should say which is which in the owner's words.

## 1. Declarations to AI

### 1.1 `Content-Signal:` in robots.txt (Content Signals Policy)

- **What.** A robots.txt line, inside a `User-agent` group, with three yes/no signals:
  `search` (build a search index and link back), `ai-input` (RAG, grounding, real-time
  answers) and `ai-train` (training or fine-tuning). An omitted signal "neither grants nor
  restricts". Cloudflare's docs also mention a trial fourth key `use=immediate|reference|full`.
- **Spec.** <https://contentsignals.org/> (policy text; the page is JavaScript-rendered and
  serves only a heading to a plain fetch -- the report should not rely on it), Cloudflare's
  announcement <https://blog.cloudflare.com/content-signals-policy/> (24 Sep 2025), docs
  <https://developers.cloudflare.com/bots/additional-configurations/managed-robots-txt/>, and
  the individual IETF draft `draft-romm-aipref-contentsignals-00` (1 Oct 2025, expired; it
  gives the vocabulary, not the robots.txt syntax).
- **Who honours it.** Nobody is bound to. Cloudflare's own words: "content signals express
  preferences; they are not technical countermeasures against scraping." Cloudflare's
  managed robots.txt inserted a policy preamble and `Content-Signal` line on "over 3.8 million
  domains" at launch, which is the adoption number to quote; it says nothing about how many
  crawlers read it.
- **Detect.** Parse robots.txt for lines whose key is `content-signal` (case-insensitive) and
  split the value on commas into `key=yes|no`. Record which group it sits in. Whether the
  policy scopes the line to its `User-agent` group (as every other robots.txt directive is)
  or reads it site-wide is **[unverified]**: Cloudflare's docs place it under a group, and
  the policy text at contentsignals.org could not be read; the report says "as written, it
  applies only to that bot" when the group is not `*`.
- **Real examples.** `vercel.com/robots.txt`: `Content-Signal: search=yes, ai-input=yes,
  ai-train=no` under `User-Agent: *`. `www.cloudflare.com/robots.txt`: `Content-Signal:
  ai-train=yes, search=yes, ai-input=yes`. anthropic.com, docs.python.org and gov.uk have none.

### 1.2 IETF AI Preferences (`aipref`): `Content-Usage`

- **What.** The standards-track successor to the above. `draft-ietf-aipref-vocab-08`
  (13 Sep 2026) defines the keys `train-ai`, `ai-use`, `search` with values `y`/`n`
  (absent = unknown, never a default). `draft-ietf-aipref-attach-05` (18 Aug 2026) attaches
  them to content two ways: an HTTP structured-field header `Content-Usage: train-ai=n` and a
  robots.txt rule `Content-Usage: [path-pattern] train-ai=n` (e.g. `Content-Usage: /ai-ok/
  train-ai=y`). No HTML meta form is defined.
- **Spec.** <https://datatracker.ietf.org/wg/aipref/documents/>.
- **Who honours it.** Both documents are still Internet-Drafts (Proposed Standard intended,
  not yet WG last call as far as the datatracker page shows). No crawler operator's public
  documentation found that says it reads `Content-Usage` **[unverified]**. The report should
  detect it and say "draft standard; no crawler documents honouring it yet".
- **Detect.** Root response header `content-usage`; robots.txt lines keyed `content-usage`.
- **Real example.** None of the five measured sites sets either form.

### 1.3 `llms.txt` and `llms-full.txt`

- **What.** A Markdown file at `/llms.txt` (or any sub-path, covering the pages under it): an
  H1 (the only required part), a blockquote summary, then H2 sections of `- [title](url):
  description` links; `llms-full.txt` inlines the whole documentation. The v2 spec
  (<https://llmstxt.org/>) now also recommends `<link rel="describedby" href="/llms.txt">` on
  pages and `<link rel="alternate" type="text/markdown">` to a page's Markdown twin, either as
  HTML `<link>` or an HTTP `Link:` header.
- **Who honours it.** No major crawler has documented reading it; Google has said it does not.
  Adoption evidence already cited in `report/score.py` (PR #95): Ahrefs' June 2026 server-log
  study of 137,000 domains found 97% of llms.txt files received no requests at all. The public
  directory at directory.llmstxt.cloud lists 3,840 sites (16 Sep 2026). It is a documentation
  convenience for coding assistants, not a discovery mechanism, which is why the score weights
  it at 5 and this PR does not raise that.
- **Detect.** GET `/llms.txt`, `/llms-full.txt`; count as present only when the body is plain
  text whose first non-blank line is an H1 (a catch-all site answers with its HTML 404 and
  status 200 -- vercel.com does this for every unknown path, 2.5 MB each). Count sections and
  links; sample five links and HEAD them.
- **Real examples.** `www.cloudflare.com/llms.txt` (17 KB, plain text) and `/llms-full.txt`
  (166 KB). `vercel.com/llms.txt` (4.7 KB) exists; its `/llms-full.txt` is the HTML shell
  (their real full file is at `/docs/llms-full.txt`). anthropic.com, docs.python.org, gov.uk:
  404.

### 1.4 `ai.txt` (Spawning)

- **What.** Spawning's 2023 proposal: a robots.txt-shaped file at `/ai.txt` whose `Disallow`
  lines name media types (`Disallow: *.jpg`, `Disallow: *.txt`) to opt out of AI training,
  generated by their web tool. **[unverified]** -- spawning.ai's pages are JavaScript-rendered
  and served nothing to the plain fetch; the format description is from memory of the 2023
  announcement and should be checked before quoting it in the UI. Honoured, as far as is
  documented, only by Spawning's own datasets tooling (Do Not Train registry).
- **Detect.** GET `/ai.txt`; present only when plain text with `User-Agent`/`Disallow` lines.
- **Real examples.** None of the five sites has one (vercel.com's is the HTML shell).

### 1.5 RSL -- Really Simple Licensing

- **What.** RSL 1.0 (Recommendation, 10 Dec 2025, <https://rslstandard.org/rsl>): an XML
  document `<rsl xmlns="https://rslstandard.org/rsl">` of `<content url>` blocks, each with
  `<license>` carrying `<permits type="usage">ai-train search</permits>`, `<prohibits>`, and
  `<payment type="crawl|subscription|attribution|free">`. Backed by the RSL Collective
  (Reddit, Yahoo, Medium, O'Reilly, Fastly among the founders per its site) **[membership list
  unverified]**.
- **Discovery.** robots.txt `License: <absolute URL>`; HTTP `Link: <url>; rel="license";
  type="application/rsl+xml"`; HTML `<link rel="license" type="application/rsl+xml">` or an
  inline `<script type="application/rsl+xml">`. The spec names no default path; `/rsl.xml` is
  a common choice, not a rule.
- **Who honours it.** A licence, not a lock: it states terms a crawler can agree to. No
  crawler operator documents enforcing it; Fastly and Cloudflare have announced support for
  serving/reading it **[unverified]**.
- **Detect.** robots `License:` lines; the root's `Link` header and `<link rel="license">`;
  GET `/rsl.xml` only as a fallback and count it only when the body parses as XML with the RSL
  namespace.
- **Real examples.** None of the five sites. (vercel.com's `/rsl.xml` is the HTML shell.)

### 1.6 TDM Reservation Protocol (TDMRep)

- **What.** W3C Community Group Final Report, 10 May 2024
  (<https://www.w3.org/community/reports/tdmrep/CG-FINAL-tdmrep-20240510/>): the EU DSM
  Directive Art. 4 machine-readable opt-out from text-and-data mining. Three carriers:
  HTTP headers `tdm-reservation: 1` and `tdm-policy: <url>`; HTML `<meta
  name="tdm-reservation" content="1">`; and `/.well-known/tdmrep.json`, a list of
  `{location, tdm-reservation, tdm-policy}` rules. `1` = rights reserved.
- **Who honours it.** Legally load-bearing in the EU (an opt-out "expressed in an appropriate
  manner"); adopted mostly by European publishers and news groups. No US crawler documents
  reading it **[unverified]**.
- **Detect.** Root headers, root meta, `/.well-known/tdmrep.json` (JSON array).
- **Real examples.** None of the five measured sites.

### 1.7 `noai` / `noimageai` robots meta (DeviantArt convention)

- **What.** DeviantArt's November 2022 convention: `<meta name="robots" content="noai,
  noimageai">`, also usable in `X-Robots-Tag`. Not part of any standard; honoured by
  DeviantArt's own tooling and a few art platforms; img2dataset (the LAION tooling) documents
  respecting `noai`/`noimageai` **[unverified]**.
- **Detect.** Tokens in `<meta name="robots">` / `googlebot` / `X-Robots-Tag`.
- **Real examples.** None of the five.

### 1.8 `X-Robots-Tag` and `<meta name="robots">` (search-snippet controls)

- **What.** The indexing directives search engines actually obey: `noindex`, `nofollow`,
  `noarchive`, `nosnippet`, `max-snippet:N`, `max-image-preview:none|standard|large`,
  `max-video-preview:N`, `noimageindex`, `notranslate`, `indexifembedded`, `unavailable_after`.
  Google's reference: <https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag>.
  Since 2023 `nosnippet`/`max-snippet` also bound what Google's AI Overviews may quote,
  making them the one *enforced* AI-related control a page has with Google.
- **Detect.** Root response `x-robots-tag` (may be `botname: directive`); `<meta name="robots">`,
  `<meta name="googlebot">`, `<meta name="bingbot">` tokens.
- **Real examples.** `vercel.com`: `<meta name="robots" content="index, max-image-preview:large">`.
  The other four set none on the root.

### 1.9 Training opt-outs by bot token (`Google-Extended`, `Applebot-Extended`, ...)

Already covered by the bots table (`report/bots.py`): `Google-Extended` and
`Applebot-Extended` are robots.txt tokens with no crawler of their own; disallowing them
withdraws content from Gemini / Apple Intelligence training while leaving search untouched.
gov.uk names `meta-externalagent` (to restrict `/search/all*`); cloudflare.com allows GPTBot,
ChatGPT-User, Google-Extended, Anthropic-AI, Claude-Web, CCBot, PerplexityBot and Cohere-ai
by name.

## 2. Discovery

### 2.1 `Sitemap:` and sitemap types

`Sitemap:` in robots.txt (sitemaps.org protocol, honoured by every search engine); sitemap
index files (`<sitemapindex>`), and the Google extensions for news (`<news:news>`), image
(`<image:image>`) and video (`<video:video>`). Already fetched by `probe_site`; this PR adds the
kind of each sitemap read (index / urlset / news / image / video) from the XML namespaces.
All five sites declare one.

### 2.2 `Crawl-delay`

Non-standard robots.txt field, honoured by Bing, Yandex and most polite crawlers, ignored by
Google. gov.uk sets `Crawl-delay: 10` for AhrefsBot. Already parsed per bot.

### 2.3 Feeds: RSS / Atom / JSON Feed autodiscovery

`<link rel="alternate" type="application/rss+xml|application/atom+xml|application/feed+json">`
in the head (RSS Board's autodiscovery convention, JSON Feed 1.1 at
<https://www.jsonfeed.org/version/1.1/>). Honoured by every feed reader and by several AI
news aggregators; a feed is the cheapest structured "what changed" a site can publish. None
of the five sites' roots advertise one (blogs under them may).

### 2.4 IndexNow

A key file `/<key>.txt` containing the key (8-128 hex/dash chars) proves ownership for
push-indexing to Bing, Yandex, Naver, Seznam, Yep (<https://www.indexnow.org/documentation>).
Not detectable without knowing the key -- **skipped** in the report, as the brief allowed.

### 2.5 Markdown twins and `Accept: text/markdown`

New in 2026 and worth recording because two of the five sites do it: vercel.com and
www.cloudflare.com answer their HTML URLs with `Content-Type: text/markdown` when the
request carries `Accept: text/markdown` (`Vary: Accept`), and advertise `<link rel="alternate"
type="text/markdown">` per page and `.md` twins for every path. The llms.txt v2 spec endorses
the link relation. Detected from the root's `<link>`s and `Link:` header; the report does not
send a second request with a different `Accept` (one more request per page for a convention
two sites use).

## 3. Agents

### 3.1 A2A Agent Card

The A2A protocol (v1.0.0, <https://a2a-protocol.org/latest/specification/>) publishes an
AgentCard at **`/.well-known/agent-card.json`** (renamed from `/.well-known/agent.json` in
v0.3; the spec text now uses only the new name). Fields: `name`, `description`, `url`,
`version`, `capabilities{streaming, pushNotifications, stateTransitionHistory}`, `skills[]`
with `id/name/description`, `protocolVersion`. Honoured by A2A clients (Google ADK, the
Linux-Foundation A2A SDKs). **Real example:** `www.cloudflare.com/.well-known/agent.json` --
"Cloudflare Site Agent", 2 skills (site-context -> llms.txt; page-markdown -> `{path}.md`),
in A2A shape at the *old* path; `/agent-card.json` 404s there. The report tries both.

### 3.2 `agents.json` (Agent Protocol / agentprotocol.ai)

A different, vendor-proposed file: `$schema: https://agentprotocol.ai/schemas/agents.json`
with `siteInfo`, `aiContent{llmsTxt, llmsFullTxt, markdownPages}`, `capabilities[]`.
**Real example:** `www.cloudflare.com/.well-known/agents.json` (4.8 KB), also advertised in
its robots.txt comments and `Link: rel="api-catalog"`. Spec provenance **[unverified]** --
agentprotocol.ai's schema page was not fetched. Reported as present with its name, not scored.

### 3.3 MCP advertisement

There is no IETF/Anthropic-specified well-known path for "this site has an MCP server"
(verified: the MCP documentation set, `modelcontextprotocol.io/llms-full.txt` read 16 Sep 2026 with revisions up to 2026-07-28, names only `/.well-known/oauth-protected-resource` and `/.well-known/mcp-registry-auth`; no site-level discovery file); conventions in the
wild are `/.well-known/mcp.json` (an `mcpServers` map in the shape of client config files)
and OAuth's `/.well-known/oauth-protected-resource` on the MCP host itself. **Real
examples:** `www.cloudflare.com/.well-known/mcp.json` -> `mcpServers.cloudflare_site` with an
HTTP transport at `/.well-known/webmcp.json` (a `webmcp/0.1` tool list); vercel.com's
`/.well-known/ai-catalog.json` (`application/ai-catalog+json`, specVersion 1.0) lists
`https://mcp.vercel.com/.well-known/oauth-protected-resource` as its MCP OAuth metadata.

### 3.4 API catalog (RFC 9727) and Agent Skills

`/.well-known/api-catalog` is a real RFC (9727, `application/linkset+json`) and vercel.com
serves one, linking its OpenAPI description. vercel.com also links
`/.well-known/agent-skills/index.json` (`schemas.agentskills.io/discovery/0.2.0`) with
downloadable skill archives and sha256 digests, and `/.well-known/ai-catalog.json`. All three
are announced in vercel.com's root `Link:` header -- the header is the discovery mechanism,
so the report reads `Link:` rels (`api-catalog`, `ai-catalog`, `agent-skills`,
`service-desc`, `describedby`, `license`, `sitemap`) rather than guessing paths.

### 3.5 `ai-plugin.json` (legacy)

OpenAI's 2023 ChatGPT-plugin manifest at `/.well-known/ai-plugin.json`; the plugin
programme closed in 2024. Detected for completeness and reported as legacy. None of the five
sites has one.

## 4. Metadata

- **JSON-LD / Schema.org.** `<script type="application/ld+json">`; the report lists distinct
  `@type`s (Organization, WebSite+SearchAction, WebPage, FAQPage, Product, Article...).
  Honoured by Google/Bing rich results and read by every serious extractor. Real:
  cloudflare.com 3 blocks in the head (Organization, WebSite, SearchAction, WebPage);
  vercel.com's (Organization, ImageObject, Person, ContactPoint, PostalAddress, Service,
  SoftwareApplication, Offer) sit in the body of the plain HTML -- a first pass that read
  only `<head>` missed them, which is why the detector walks the whole document.
- **OpenGraph / Twitter cards.** `<meta property="og:*">`, `<meta name="twitter:*">`
  (<https://ogp.me/>). Honoured by every link-unfurler (Slack, iMessage, LinkedIn, X) and
  used by assistants for titles/images. All five roots carry OG; docs.python.org and gov.uk
  omit Twitter cards.
- **`hreflang`.** `<link rel="alternate" hreflang="xx">`; Google/Bing/Yandex use it to pick
  the language edition. cloudflare.com: 10.
- **`rel=canonical`.** All five roots set one; docs.python.org points its root at
  `/3/index.html`.
- **`<meta name="robots">`** -- see 1.8.

## 5. Trust and app metadata

- **`security.txt` (RFC 9116).** `/.well-known/security.txt` (the `/security.txt` fallback
  is permitted); fields `Contact` (required), `Expires` (required by the RFC), `Policy`,
  `Canonical`, `Preferred-Languages`, `Hiring`. Read by security researchers and scanners.
  Real: vercel.com (Expires 2027-05-27), cloudflare.com (no `Expires` -- non-conforming),
  anthropic.com, gov.uk (both paths); docs.python.org none.
- **`humans.txt`.** `/humans.txt` (<https://humanstxt.org/>): credits, no machine consumer.
  gov.uk has one. Detected, not scored.
- **Web app manifest.** `<link rel="manifest">` -> `application/manifest+json` with `name`,
  `start_url`, `display`, `icons` (W3C). Browsers use it for install; no crawler needs it.
  vercel.com: `/manifest.webmanifest`, "Vercel", standalone.
- **Speculation rules.** `<script type="speculationrules">` (WICG, Chrome prerender). A
  performance hint, no machine-readable declaration; recorded because the brief asked. None
  of the five roots.

## 6. Crawler-side mechanisms the report can only mention

- **Web Bot Auth / HTTP Message Signatures.** RFC 9421 signatures on crawler requests with
  `Signature`, `Signature-Input` and `Signature-Agent` headers, keys published by the *crawler*
  in an `http-message-signatures-directory` (drafts `draft-meunier-web-bot-auth-architecture`,
  `draft-meunier-http-message-signatures-directory`; Cloudflare, 15 May 2025). It is
  something a bot presents, not something a site publishes; a site cannot be measured for it
  without impersonating a signed bot, which the engine refuses. The report explains this
  under "not measured".
- **Pay per crawl (Cloudflare, 1 Jul 2025).** A site returns `402 Payment Required` with a
  `crawler-price` header to registered crawlers that did not offer `crawler-max-price`; paid
  responses carry `crawler-charged`. Observable by *registered* crawlers only; the engine is
  not one, so a 402 on the root is recorded as such but the price header is unlikely to be
  seen. None of the five sites answered 402.

## 7. What this means for the score

The brief says: keep the total at 100, do not weight llms.txt above 5. The structured-data
sub-score (10 points) already scores JSON-LD and title/description/lang. This PR leaves the
eight weights unchanged and adds *no* new sub-score: declarations to AI are choices, not
virtues (a site that says `ai-train=no` is not less ready), agent cards are rare enough that
scoring their absence would penalise 99% of the web, and the existing metadata sub-score
covers what search engines actually reward. Instead every signal carries a plain-words
`meaning` and `who_honours` so the owner can decide. The one scoring change: the metadata
sub-score's 4 "page-fields" points now also count OpenGraph presence on the root (title,
description, lang, og) so a site that unfurls correctly in Slack and assistants gets credit
-- documented in `docs/site-report`.
