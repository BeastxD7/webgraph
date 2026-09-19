"""Every setting webgraph has, as a name and a value.

Nothing else lives here: no classes, no functions. Each setting is a plain constant with a
comment saying what it does and what the options are. The code that uses a setting imports
it from here; the dataclasses that group settings for a call (`FetchConfig`, `SiteConfig`,
...) live beside the code they configure and take their defaults from these names.

Environment variables (`WEBGRAPH_*`) override the values in the "Deployment" section at
process start; see `webgraph.settings`. Everything else is changed by editing this file or
by passing a config object to the call.

Most values were set by measurement against the benchmarks under `benchmark/`; the comment
says so where it matters. Change with the same care.
"""

# ======================================================================================
# Fetching (plain HTTP)
# ======================================================================================

# Seconds to wait for a plain HTTP response.
FETCH_TIMEOUT_SECONDS = 20.0

# Redirect hops to follow before giving up.
FETCH_MAX_REDIRECTS = 5

# Largest response body read, in bytes. Bigger than this is not a page.
FETCH_MAX_BYTES = 32 * 1024 * 1024

# Negotiate HTTP/2 when the server offers it (falls back to HTTP/1.1 on its own).
FETCH_HTTP2 = True

# Extra attempts after a status in RETRY_STATUSES or a transport error. 0 = never retry.
FETCH_RETRIES = 1

# HTTP statuses that mean "later", not "no". Retried once, honouring Retry-After.
RETRY_STATUSES = frozenset({429, 503})

# Longest Retry-After (seconds) honoured inline. A server asking for a minute is asking to
# be crawled later, not to have a thread held open.
MAX_RETRY_WAIT_SECONDS = 5.0

# The browser identity in the User-Agent, followed by webgraph's own name so a site can
# still tell who is calling. Browser-shaped because several CDNs refuse a bare bot string.
USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# The full User-Agent header sent with every request.
USER_AGENT = f"{USER_AGENT_BROWSER} webgraph/0.1 (+https://github.com/webgraph/webgraph)"
# What follows the operator's contact in a declared User-Agent (`DEPLOY_CONTACT`). No URL:
# measured on sec.gov, 14 Sep 2026, `Name email webgraph/0.1` is admitted and any form
# carrying `(+https://…)` is refused with the same demand.
DECLARED_AGENT_SUFFIX = "webgraph/0.1"

# ======================================================================================
# Rendering (real browser)
# ======================================================================================

# Milliseconds a navigation may take before the page is read as-is (or refused if empty).
RENDER_TIMEOUT_MS = 30_000

# When the navigation counts as finished. Options: "commit", "domcontentloaded", "load",
# "networkidle". "load" -- "networkidle" never fires on sites with analytics beacons or
# polling; measured, it timed out on 5 of 24 real sites.
RENDER_WAIT_UNTIL = "load"

# Viewport in CSS pixels. Width decides reading order: a narrow viewport collapses a
# multi-column layout into one column, which changes the correct answer.
RENDER_VIEWPORT_WIDTH = 1440
RENDER_VIEWPORT_HEIGHT = 900

# Milliseconds to wait after load for hydration and layout to settle before measuring.
RENDER_SETTLE_MS = 900

# Click through a first-run interstitial (persona picker, age gate) that blocks the page
# from mounting. One guarded click, discarded unless the page measurably improves.
RENDER_DISMISS_GATES = True

# Open collapsed content before measuring, without clicking: <details>, ARIA disclosures,
# tab panels, and panels a control names (data-bs-target, href="#id"). Never inside
# nav/header/footer or a menu. Measured 19 Sep 2026 on the fidelity board: recall
# unchanged (Chromium's own text never counts a closed panel), extra words +0.001 mean,
# +0.027 at most (arxiv.org's bibliographic-tools tabs, which are the page's own). What
# it changes is that content reachable by a click is measured and ordered where it sits
# rather than anchored after its neighbour.
RENDER_REVEAL_COLLAPSED = True

# Run the browser without a window.
RENDER_HEADLESS = True

# Reuse the calling thread's browser rather than launching one per page.
RENDER_REUSE_BROWSER = True

# Resource types the browser does not download. Fonts deliberately: metrics shift by a
# pixel or two and reading order does not care. Options: any Playwright resource type.
RENDER_BLOCK_RESOURCES = ("image", "media", "font")

# A page with fewer visible characters than this after a navigation timeout is not a
# salvaged page, it is a server error rendered as a document.
MIN_SALVAGED_TEXT = 200

# Network requests recorded per render, for the technology profiler. Enough to see the
# stack, not enough to hold a video site's beacons in memory.
MAX_RECORDED_REQUESTS = 400

# A page is treated as gated (see RENDER_DISMISS_GATES) only when it has at most this
# much text and this many internal links, and a click must grow the text by this factor
# to be kept.
GATE_MAX_TEXT = 4000
GATE_MAX_LINKS = 1
GATE_MIN_GAIN = 1.5

# Click collapsed content open when nothing else reaches it: tabs, accordions and "show
# more" panels wired in JavaScript alone, which `reveal.js` (attributes only) cannot open.
# Runs after the page was measured once, only when at least CLICK_MIN_HIDDEN_WORDS words
# are still hidden outside the site's chrome; tries at most CLICK_MAX_CANDIDATES controls
# with the page's own click(), stops after CLICK_MAX_FUTILE that opened nothing. Every
# element a click opened is forced visible again and the page measured a second time;
# that measurement is kept only if the page still holds what it held.
RENDER_CLICK_COLLAPSED = True
CLICK_MIN_HIDDEN_WORDS = 30
CLICK_MAX_CANDIDATES = 10
CLICK_MAX_FUTILE = 4
CLICK_SETTLE_MS = 200
# The clicks happen after the page was measured once, so a click that navigates or
# empties the page costs nothing: the second measurement is simply not taken. The
# clicking is given this long in all.
CLICK_BUDGET_MS = 6_000

# ======================================================================================
# Resolving a page (deciding what came back)
# ======================================================================================

# Statuses meaning the page does not exist. Never rendered -- a browser renders a 404 page
# perfectly happily and reports "Not Found" as content.
MISSING_STATUSES = frozenset({404, 410})

# Statuses that mean something a person can act on, said in words.
BLOCKING_STATUSES = {
    401: "the page requires a sign-in",
    402: "the site answered 'payment required', which is how some of them refuse automated clients",
    403: "the site refused this client",
    429: "the site is rate-limiting this client",
    451: "the page is blocked for legal reasons",
    503: "the site said it was too busy, which is also how several of them refuse bots",
}

# A page shorter than this that says what walls say ("you've been blocked", "verify you
# are human") is refused as a block page. Longer pages merely mentioning those words are
# pages.
MAX_BLOCK_PAGE_CHARS = 1_500
# When one of the two fetches (plain, browser) is served a wall, the other stands in for
# the page only if it has at least this many words of its own. old.reddit.com answers the
# browser with the wall and the plain fetch with a login redirect whose only words are
# "Skip to main content"; that is not the page, and the merge is refused as the wall it
# holds rather than returned as a two-block success.
MIN_PAGE_BESIDE_WALL_WORDS = 20
# A fetch that ends on a different URL than it asked for, and whose final path holds one of
# these segments, was redirected to a login page: old.reddit.com's thread pages go to
# `/login/?reason=lor2&dest=…`, linkedin.com/feed to `/uas/login?session_redirect=…` (plain)
# and `/login/?session_redirect=…` (browser). Matched on whole path segments, so
# `/blog/how-to-login` is a post and `/uas/login` a login page; a marker with two segments
# (`/session/new`) has to appear as those two segments in that order. The redirect has to be
# a real one -- a trailing slash, `www.` or scheme change is not a redirect to anything --
# and a page asked for at a login URL is the login page, not a wall.
LOGIN_PATH_MARKERS = (
    "/login",
    "/login.php",
    "/login.aspx",
    "/signin",
    "/sign-in",
    "/sign_in",
    "/sso",
    "/auth",
    "/authenticate",
    "/oauth",
    "/oauth2",
    "/authorize",
    "/accounts/login",
    "/session/new",
    "/sessions/new",
    "/user/login",
    "/users/sign_in",
    "/wp-login.php",
)
# A login page also gives itself away by the parameter that says where to go afterwards:
# `dest=` (reddit), `session_redirect=` (linkedin), `next=` (Django), `redirect_to=`
# (WordPress), `returnUrl=` (ASP.NET), `continue=` (Google). Counted only when the value
# names the URL that was asked for, so a `?redirect=` on an unrelated page is not a login.
# Compared case-insensitively with `_` and `-` removed (`returnUrl`, `return_url`, `ReturnURL`).
LOGIN_RETURN_PARAMS = (
    "dest",
    "next",
    "redirect",
    "redirectto",
    "redirecturi",
    "redirecturl",
    "return",
    "returnto",
    "returnurl",
    "continue",
    "sessionredirect",
    "goto",
)
# A login redirect is a wall when the document it lands on holds a password field, or has
# fewer words than this: a login page has a form and a footer, not an article. Measured:
# old.reddit.com's login shell 4 words (plain) and 26 (the browser's Cloudflare wall on it),
# linkedin.com's 52-54 with two password fields; news.ycombinator.com's front page 711 and
# github.com/python/cpython 1,684-2,031, neither redirected anywhere. A long page that
# happens to hold a sign-in box (a shop's header) is a page.
MAX_LOGIN_PAGE_WORDS = 150

# ======================================================================================
# Parsing markup into blocks
# ======================================================================================

# Largest HTML document parsed, in bytes.
MAX_DOCUMENT_BYTES = 32 * 1024 * 1024

# A page with fewer visible words than this outside <noscript> is a JavaScript shell ...
NOSCRIPT_SHELL_MAX_WORDS = 150
# ... and its <noscript> is used as the page when it holds at least this many.
NOSCRIPT_CONTENT_MIN_WORDS = 100

# Layout tables (a page built out of <table>) are told from data tables by shape. A cell
# longer than this many characters is page content, not a datum.
LONG_CELL_CHARS = 200
# A grid needs at least this many rows and columns to be data.
MIN_GRID = 2
# At least this share of cells must hold something.
MIN_FILLED_SHARE = 0.4
# More than this share of empty rows and it is spacing, not data.
MAX_EMPTY_ROW_SHARE = 0.2

# An inline <svg> is read for its <text> labels (a syntax diagram, a flow chart, a chart's
# axis) when it has at least this many <text> nodes ...
SVG_MIN_TEXT_NODES = 2
# ... or at least this many words across them. Below both it is an icon whose one label
# ("Search", "Menu") the button beside it already says.
SVG_MIN_WORDS = 3

# ======================================================================================
# Reading order (geometric XY-cut)
# ======================================================================================

# Whitespace bands are measured in multiples of the median block height, so one setting
# fits a dense sidebar and an airy landing page.
ORDER_MIN_ROW_GAP_RATIO = 0.6  # a vertical gap this big separates rows
ORDER_MIN_COL_GAP_RATIO = 1.0  # a horizontal gap this big separates columns
ORDER_MIN_ABSOLUTE_GAP = 8.0  # floor in CSS pixels, for tiny-text pages
ORDER_MAX_DEPTH = 24  # recursion guard; deeper cuts are ordered positionally

# Share of blocks that must carry measured geometry before geometry leads the ordering.
# Set by blinding runs of blocks on fully measured pages and scoring pair order.
ORDER_MIN_MEASURED_SHARE = 0.3

# ======================================================================================
# Content selection (the main-content boundary)
# ======================================================================================

# Per-block cost scales with the page's own mean block length instead of a constant.
# Measured on WCXB: +0.035 F1 over a fixed cost, better on all seven page types.
CONTENT_ADAPTIVE_COST = True
CONTENT_COST_RATIO = 0.60  # cost = clamp(ratio * mean block words, floor, ceiling)
CONTENT_COST_FLOOR = 5.0
CONTENT_COST_CEILING = 18.0
# A single block counts at most this many words towards the mean the cost is drawn from.
# wordpress.org's release post lists 630 contributor names in one 2,100-word paragraph; it
# set the cost to the ceiling and the boundary step kept 9 of the post's 54 blocks.
CONTENT_COST_BLOCK_CAP = 400
CONTENT_BLOCK_COST = 13.0  # the fixed cost, when CONTENT_ADAPTIVE_COST is False

# A paragraph of at most this many words directly before a code block is the code's caption
# ("Start the service:", "for 64bit:") and, like the code, never costs the run (floored at 0).
CODE_CAPTION_MAX_WORDS = 8

# Words credited to a heading beyond its own count -- headings are short and are content.
CONTENT_HEADING_BONUS = 4.0
# Share of a table's or code block's words credited even when they look link-dense.
CONTENT_STRUCTURAL_CREDIT = 0.5
# Accumulated cost a run may absorb before it restarts, as a multiple of the block cost.
CONTENT_BRIDGE = 0.0
# Inside a <main> landmark, count linked words as content rather than as chrome.
CONTENT_TRUST_MAIN_LINKS = True
# Score repeated sibling items (product cards, listing rows) as one unit.
# Options: "off", "all", "linked".
CONTENT_GROUP_REPEATS = "off"
CONTENT_MIN_GROUP_SIZE = 3  # fewer repeated siblings than this is not a grid
CONTENT_GROUP_MIN_SHARE = 0.3  # a group is scored as a unit only above this share of words
# Drop the river of other stories under an article by its heading ("More from World",
# "Trending News", "Top Stories", "Most Read") before the run is chosen. The vocabulary is
# deliberately narrow: an article's own FAQ, Q&A, Related and Comments sections count as
# content on WCXB and pruning them measured worse. True or False.
CONTENT_PRUNE_RIVERS = True
# A <blockquote> whose text is already on the page above it (a forum reply quoting the post
# it answers) is dropped before the boundary is drawn. True or False.
CONTENT_DROP_REPEATED_QUOTES = True
# A block of at least PIPELINE_RESTATED_MIN_WORDS words whose six-word shingles are already
# PIPELINE_RESTATED_SHARE present across the *other* blocks -- with no single block supplying
# PIPELINE_RESTATED_SINGLE_MAX of them -- is the page restating itself (an `articleBody`
# microdata div after the paragraphs, a reply quoting the whole opening post) and is dropped
# before the reading order is fixed. The single-block cap keeps two near-identical code
# samples or tables, which are revisions, not restatements.
PIPELINE_RESTATED_MIN_WORDS = 150
PIPELINE_RESTATED_SHARE = 0.7
PIPELINE_RESTATED_SINGLE_MAX = 0.5
# Never return less than this share of the document's words.
CONTENT_MIN_RUN_SHARE = 0.02
# When the boundary step cut the page's title and it is put back, the blocks between the
# title and the body (byline, standfirst, opening sentence) come back with it -- if there
# are at most this many, and at most this share of them are list items (a menu under the
# title is not a lead).
CONTENT_LEAD_MAX_BLOCKS = 12
CONTENT_LEAD_MAX_LIST_SHARE = 0.5

# ======================================================================================
# Site chrome (blocks repeated across a site's pages)
# ======================================================================================

# A block seen on at least this share of a site's pages is chrome.
CHROME_THRESHOLD = 0.9
# Pages a crawl must have before cross-page chrome can be judged at all.
CHROME_MIN_PAGES = 6
# Never remove more than this share of a page as chrome.
CHROME_MAX_REMOVAL = 0.5
# A template slot (same position, different text) must be present on this share of pages.
CHROME_SLOT_PRESENCE = 0.6
# A <nav>/<footer> landmark shorter than this is trusted as declared and removed.
CHROME_MIN_LANDMARK_CHARS = 200
# The comments under a page are stripped only when at least this many words of prose
# (paragraphs of 15+ words that are not mostly links) remain outside them -- a story with a
# thread beneath it. Below it the comments are the page (a Hacker News comment page, a
# GitHub issue) and stay whatever the page type.
CHROME_MIN_COMMENT_HOST_WORDS = 60
# A <main> landmark is trusted only if it holds at least this many words and this share
# of the page; otherwise it is decoration and ignored. The share was 0.5; swept on WCXB dev
# (0.5 / 0.3 / 0.2 / 0.1 -> 0.8503 / 0.8522 / 0.8531 / 0.8532 overall), 0.2 keeps articles
# at their best and lets a page whose mega-menu outweighs its article still be scoped.
# After the main landmark, the page's dominant <article> element: trusted as the content's
# extent when it holds at least this many words, this share of the page, and this many
# times the words of the next largest <article> (news teasers are often <article>s too; a
# forum thread of equal posts never qualifies). Per-type policies can switch it off.
CHROME_ARTICLE_MIN_WORDS = 100
CHROME_ARTICLE_MIN_SHARE = 0.15
CHROME_ARTICLE_DOMINANCE = 3.0
CHROME_MAIN_MIN_WORDS = 100
CHROME_MAIN_MIN_SHARE = 0.2

# ======================================================================================
# Page type (the router)
# ======================================================================================

# Below this confidence the router says "unknown" and the default policy applies. Out of
# fold it is right 86% of the time above 0.5 and 44% below.
ROUTER_MIN_CONFIDENCE = 0.5

# ======================================================================================
# Crawling a whole site
# ======================================================================================

# Pages to attempt before the crawl stops, refusals included. 0 = unbounded, until the
# frontier is exhausted -- an explicit ask, never the default: a whole-site run of
# vtu.ac.in with no cap ran six hours and held six gigabytes (PR #87, #94).
CRAWL_MAX_PAGES = 500

# Seconds a crawl may run before it stops, measured from the start of the analysis and
# checked as each page lands. 0 = no time limit. The `done` event says
# `stopped_by: "time"` when this ended it.
CRAWL_MAX_SECONDS = 3600

# Queued addresses beyond which the frontier stops accepting new ones. Discovery on a
# large site outruns extraction by an order of magnitude (vtu.ac.in: 17,126 found, 12,761
# fetched), and every queued address is held in memory. 0 = no limit.
CRAWL_MAX_QUEUE = 20_000

# Fetch links to PDFs and other files. Off, they are counted (`discovered_kinds`), cited
# (`skipped_urls`, with the page that linked to each) and never requested: the engine has
# no document pipeline, so a fetched PDF is refused, and 5,730 of them cost a third of a
# six-hour run. On, `.pdf` links are queued as pages were before (#94).
CRAWL_FETCH_FILES = False

# How many skipped file addresses the `done` event lists in full (with their citations).
# The count by kind is always complete; the list is capped so one event cannot carry
# thousands of lines.
CRAWL_SKIPPED_URLS_REPORTED = 200

# Pages fetched in parallel within one crawl.
CRAWL_CONCURRENCY = 4

# Pause between fetches per worker, in seconds. Per worker: with four workers this alone
# allows four requests a second. The per-host interval below is what bounds the site's load.
CRAWL_DELAY_SECONDS = 0.3

# Minimum seconds between two requests to the same host, across every worker of a crawl.
# 1.0 = at most one page a second per host, whatever the concurrency; the site's
# `Crawl-delay` replaces it when larger. Under `union` a page is two requests (plain and
# rendered) made together; the interval spaces pages, not requests.
CRAWL_HOST_INTERVAL_SECONDS = 1.0

# How many links away from the root the crawl goes. 0 = the root alone; 1 = the root and
# everything it links to; and so on. The crawl is breadth-first: every page at depth n is
# fetched before any page at depth n+1.
CRAWL_MAX_DEPTH = 12

# True: stay on the root's host (www.example.com and example.com are one host).
# False: also follow subdomains (blog.example.com, shop.example.com). Never other sites.
CRAWL_STRICT_DOMAIN = True

# True: stay under the start address's path -- a crawl of example.com/docs/ follows
# /docs/... and turns /blog/... away as `not-included`. False: the whole site, whatever
# address it started from. Off, because a site is the unit this engine reads.
CRAWL_WITHIN_PATH = False

# Ask Common Crawl's latest index which addresses it has seen on the host, once, at the
# start of a crawl (two requests to index.commoncrawl.org, ~1-2 s; nothing is asked of the
# site). Reported in the run's `discovery` as its own fact -- "last seen by Common Crawl",
# months stale by design -- never merged into what the crawl found.
CRAWL_COMMON_CRAWL = True

# Also queue what Common Crawl listed, at depth 1, cited `via: common-crawl`. Off: a
# stale listing is full of pages that are gone, and every one would be fetched and
# recorded as a 404. On, for a site with no sitemap whose pages nothing links to.
CRAWL_SEED_FROM_COMMON_CRAWL = False

# Paths to follow, as regular expressions searched in the address's path (never the host),
# comma-separated -- "^/docs/, ^/blog/". Empty means no restriction. When set, only
# matching addresses are crawled; the rest are counted as `not-included` in the run's
# `refused`, with the first of them named.
CRAWL_INCLUDE_PATHS = ""

# Paths to turn away, the same shape -- "/publications/, \?page=". A match is refused as
# `excluded`, whatever else says, and counted in the run's `refused`.
CRAWL_EXCLUDE_PATHS = ""

# Check each sitemap URL with a cheap request before spending a page on it.
CRAWL_VERIFY_INVENTORY = True

# Discover pages by following links, as well as by reading the sitemap.
CRAWL_FOLLOW_LINKS = True

# URLs harvested by link-following before verification.
CRAWL_DISCOVERY_LIMIT = 400

# URLs read from sitemaps, at most.
CRAWL_SITEMAP_LIMIT = 50_000

# Honour robots.txt on a crawl: turn away at the frontier what the file disallows for this
# client. Off by default since 19 Sep 2026, by the owner's decision: the engine explores
# and reads every page it can reach, and a caller who wants the site's rules obeyed asks
# for it (`SiteConfig.respect_robots`, the API's `crawl.respect_robots`, Settings). The
# file is still read -- for its sitemaps, and for the site report, which measures what
# the site declares and always obeys it. Politeness is not a robots rule and is never
# off: one page a second per host, and the file's `Crawl-delay` when larger.
CRAWL_RESPECT_ROBOTS = False

# Honour robots.txt for a single page (`resolve_page`, `/api/text`). Same default and
# same reason as the crawl. When on, a disallowed page is refused with the file and the
# rule quoted and the sanctioned paths named (`ROBOTS_SANCTIONED_SOURCES`). Per request:
# `FetchConfig.respect_robots`, the API's `fetch.respect_robots`.
PAGE_RESPECT_ROBOTS = False

# The name this client answers to in a robots.txt `User-agent:` line. `urllib.robotparser`
# takes the first `/`-split token of the User-Agent string, which for the browser-shaped
# agent is "mozilla" -- so the rule is asked for by this token, not by the header.
ROBOTS_AGENT_TOKEN = "webgraph"

# How long a host's robots.txt is trusted before it is fetched again.
ROBOTS_CACHE_SECONDS = 3600

# How much of a site's robots.txt the crawl's `discovery` event carries, so a reader can
# see the file itself. Enough for any real file (Wikipedia's, the longest seen, is ~24k;
# most are under 1k); the rules that apply to this client are always sent whole.
DISCOVERY_ROBOTS_TEXT_CHARS = 4_000

# Where a site that disallows automated reading offers its content instead, named in the
# refusal. Only the ones that could be cited; a hint the engine cannot stand behind is noise.
ROBOTS_SANCTIONED_SOURCES = {
    "stackoverflow.com": "the Stack Exchange API (https://api.stackexchange.com/docs)",
    "reddit.com": "the Reddit Data API (https://www.reddit.com/dev/api)",
}

# Also produce content_markdown: the page with landmarks, site chrome and boilerplate
# removed.
CRAWL_REMOVE_CHROME = True

# Also draw the main-content boundary when producing content_markdown.
CRAWL_MAIN_CONTENT = True

# How each page is fetched. Options: None (measure the root and decide per site),
# "static-only", "rendered-only", "union" (both, merged -- the completeness path).
CRAWL_STRATEGY = None

# Sitemap indexes nest; read at most this many sitemap files.
MAX_SITEMAP_DOCUMENTS = 20

# Anchor text longer than this is a card or a paragraph wrapped in a link, not a label.
MAX_ANCHOR_CHARS = 160

# Distinct URLs returning byte-identical text before the crawl warns of a gate it could
# not open.
IDENTICAL_CONTENT_WARNING = 3

# ======================================================================================
# Watch (change monitoring)
# ======================================================================================

# A block whose text is a date, a time or a counter -- rather than a sentence that contains
# one -- is left out before two versions of a section are compared. Each pattern is removed
# from the block's text; if fewer than WATCH_NOISE_MIN_WORDS alphabetic words remain, the
# block was the pattern and is ignored; a block no pattern touches is always compared.
# Case-insensitive. The rule is deliberately narrow: "Results announced on 12/09/2026" is a
# sentence and is compared; "12/09/2026" alone, "Last updated: 12 Sep 2026",
# "Visitors: 1,204,551" and "10:42 am" are not. Known edge: a block that is only a label
# and a four-digit number ("Total seats: 1200") reads as a counter and is ignored.
WATCH_NOISE_PATTERNS = (
    # Dates: 12/09/2026, 2026-09-12T10:42:00Z, 12.09.26, 12 Sep 2026, September 12, 2026.
    r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b",
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?\b",
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?,?\s+\d{2,4}\b",
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{2,4}\b",
    # A weekday only when written as a date's prefix: "Friday, 12 ..." or "Fri 12".
    r"\b(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|nesday|rsday|urday)?\b,?(?=\s+\d)",
    # Times: 10:42, 10:42:07, 10:42 am, 22:15 IST.
    r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?\s*(?:[A-Z]{2,4}|UTC[+-]\d{1,2}(?::\d{2})?)?\b",
    # The label of a timestamp: "Last updated on", "Published:", "Page generated in".
    r"\b(?:last\s+)?(?:updated|modified|published|posted|generated|revised|refreshed)(?:\s+on|\s+at|\s+in)?\b:?",
    # A counter: a label beside a number, either way round; "You are visitor number 1204".
    r"\b(?:visitors?|views?|hits|visits|online|users\s+online|page\s*views?|total\s+visitors?|counter)\b\s*:?\s*\d[\d,.]*",
    r"\b\d[\d,.]*\s*(?:visitors?|views?|hits|visits|online|page\s*views?)\b",
    r"\byou\s+are\s+visitor\s+(?:number|no\.?)?\s*\d[\d,.]*",
    # Counter-shaped numbers on their own: four or more digits, or thousands separators.
    r"\b\d{1,3}(?:,\d{3})+\b",
    r"\b\d{4,}\b",
    # Relative times.
    r"\b\d+\s+(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago\b",
    r"\bjust\s+now\b",
    # Copyright lines.
    r"(?:©|\(c\)|copyright)\s*\d{4}(?:\s*[-\u2013]\s*\d{4})?",
)

# Alphabetic words a block must keep, once the noise patterns are removed, to be compared.
WATCH_NOISE_MIN_WORDS = 3

# Characters of a section's text kept on each side of a recorded change. Provenance is the
# heading and the page; the text is context, and a 40 kB table is not context.
WATCH_SECTION_TEXT_CHARS = 2_000

# Sections reported per changed page before the page counts as rewritten.
WATCH_MAX_SECTIONS_PER_PAGE = 40

# ======================================================================================
# Knowledge graph
# ======================================================================================

# A section longer than this many characters is split; shorter than the minimum is merged.
GRAPH_MAX_SECTION_CHARS = 6_000
GRAPH_MIN_SECTION_CHARS = 40

# An entity name must be this long, this short, and appear on at most this share of pages
# (a name on every page is the site's name, not an entity).
GRAPH_MIN_NAME_CHARS = 4
GRAPH_MAX_NAME_CHARS = 60
GRAPH_MAX_NAME_PAGE_SHARE = 0.6

# A code identifier must be used this many times to count as an entity.
GRAPH_MIN_CODE_USES = 2
# This many pages must agree on an anchor text before it names an entity.
GRAPH_MIN_ANCHOR_AGREEMENT = 2

# Retrieval (assembling context under a token budget).
GRAPH_CHARS_PER_TOKEN = 4.0  # rough tokeniser: characters per token
GRAPH_BM25_B = 0.75  # BM25 length normalisation
GRAPH_HEADING_UBIQUITY = 0.5  # a heading on this share of pages carries no signal
GRAPH_DEDUP_PREFIX_CHARS = 300  # sections sharing this prefix are duplicates
GRAPH_PAGE_EVIDENCE_WEIGHT = 0.0  # weight of page-level matches; 0 = sections only
GRAPH_FEEDBACK_DISCOUNT = 0.5  # how much a "not useful" mark demotes a section
GRAPH_MENTION_WEIGHT = 0.25  # weight of an entity mention against a text match
GRAPH_HEADING_WEIGHT = 3  # a match in a heading counts this many times

# ======================================================================================
# WebGraph: the inferred knowledge graph (`webgraph.kg`, behind WEBGRAPH_KG)
# ======================================================================================

# A section shorter than this many characters is not sent to the model: too little text
# to state a fact with a verifiable quote, and the prompt overhead dwarfs it.
KG_MIN_SECTION_CHARS = 120

# Sections extracted in parallel. Each is one model call; four keeps a laptop's local
# model busy without tripping a hosted provider's rate limit.
KG_CONCURRENCY = 4

# Caps a build stops cleanly at, reporting truncated=true. 0 = no cap. Input tokens are
# estimated at four characters each before any call is made (the `estimate` event).
KG_MAX_PAGES = 0
KG_MAX_SECTIONS = 0
KG_MAX_INPUT_TOKENS = 2_000_000
KG_MAX_USD = 0.0

# Extra extraction passes over each section ("gleaning"). GraphRAG's default of one
# doubles the bill for a few more relations; off here, and measured before it is turned on.
KG_GLEANINGS = 0

# Two names for one entity are merged when their 3-gram shingle sets overlap by at least
# this Jaccard score and the type agrees. 0.9 catches typos and spacing, not synonyms.
KG_MERGE_JACCARD = 0.9

# An entity named on more than this share of pages is kept but never expanded through: it
# is the site's own name, and a hop through it reaches everything, which reaches nothing.
KG_GENERIC_PAGE_SHARE = 0.6

# Retrieval: seeds from the entity and fact indexes, then this many hops of expansion,
# capped so a hub cannot flood the evidence set; `decay` is the per-hop score multiplier.
KG_MAX_HOPS = 2
KG_HOP_DECAY = 0.5
KG_MAX_ENTITIES = 60
KG_MAX_RELATIONS = 150

# Evidence handed to the answer model, and the share of it reserved for rows reached by
# expansion rather than by the seed match (the `Budget.neighbour_share` lesson).
KG_MAX_EVIDENCE = 24
KG_GRAPH_EVIDENCE_SHARE = 0.35

# Model output longer than this many characters per section is discarded as runaway.
KG_MAX_OUTPUT_CHARS = 40_000

# ======================================================================================
# Technology profiling
# ======================================================================================

# Script bundles fetched to fingerprint frameworks, and the total bytes read.
PROFILE_MAX_SCRIPTS = 4
PROFILE_MAX_TOTAL_BYTES = 3_000_000

# ======================================================================================
# Site report (what a site shows people, what it shows machines, how ready it is for agents)
# ======================================================================================

# Pages a report samples: the root, then the first internal links the root offers, one per
# path prefix where the root links to several sections. Each is fetched both ways.
REPORT_PAGES = 5

# Most pages one report may sample, whatever the caller asks for.
REPORT_MAX_PAGES = 10

# Seconds between the report's own requests to one host -- pages, robots.txt, llms.txt,
# sitemaps, dead-link checks. One a second at most; a report is a courtesy call.
REPORT_REQUEST_INTERVAL_SECONDS = 1.0

# Internal links checked for a dead answer (HEAD, GET on 405; status >= 400) per sampled
# page. Each address is checked once per report, however many pages link to it.
REPORT_DEAD_LINK_CHECKS_PER_PAGE = 30

# Distinct external hosts linked from hidden or off-screen elements before the report
# calls it a likely SEO-spam injection. vtu.ac.in carried ~60 such links to dozens of
# gambling hosts per page (14 Sep 2026); a site's own off-canvas menu links to one host.
REPORT_SPAM_MIN_HOSTS = 5

# A CMS release older than this many years, when the version is known and its release
# date is in the report's table, is flagged as an outdated stack.
REPORT_STACK_OLD_YEARS = 3

# ======================================================================================
# Run traces
# ======================================================================================

# Longest string kept in a trace record. Content belongs in the result, not the log.
TRACE_MAX_VALUE_CHARS = 2_000

# ======================================================================================
# Deployment -- each overridable by the environment variable named beside it
# ======================================================================================

# WEBGRAPH_MAX_PAGES: hard ceiling on pages per crawl, whatever a client asks. 0 = none.
DEPLOY_MAX_PAGES = 0

# WEBGRAPH_MAX_CONCURRENCY: ceiling on parallel fetches within one crawl. 0 = none.
DEPLOY_MAX_CONCURRENCY = 0

# WEBGRAPH_MAX_CONCURRENT_RENDERS: browser pages open at once across the API.
DEPLOY_MAX_CONCURRENT_RENDERS = 2

# WEBGRAPH_MAX_CONCURRENT_CRAWLS: crawls the API runs at once; the rest queue.
DEPLOY_MAX_CONCURRENT_CRAWLS = 3

# WEBGRAPH_MAX_BROWSERS: live browsers across the process, ~150 MB each. Six suits 16 GB.
DEPLOY_MAX_BROWSERS = 6

# WEBGRAPH_TRACE_DIR: where run traces are written. None = the system temp directory.
DEPLOY_TRACE_DIR = None

# WEBGRAPH_TRACE: a single trace file for library and CLI runs. None = no trace.
DEPLOY_TRACE_FILE = None

# WEBGRAPH_GRAPH_DIR: where crawled graphs are kept. None = ~/.cache/webgraph/graphs.
DEPLOY_GRAPH_DIR = None

# WEBGRAPH_KG: serve the knowledge-graph routes (/api/graph/*) and CLI. Off = the routes
# answer 404 and say so. Off by default until the benchmark in benchmark/kg beats BM25.
DEPLOY_KG = False

# WEBGRAPH_KG_DIR: where per-site knowledge graphs (SQLite) are kept. None =
# ~/.cache/webgraph/kg.
DEPLOY_KG_DIR = None
# WEBGRAPH_WATCH_DB: the SQLite file that holds watches, their runs, pages and changes.
# None = ~/.cache/webgraph/watch.sqlite3 (XDG_CACHE_HOME respected).
DEPLOY_WATCH_DB = None

# WEBGRAPH_ALLOWED_ORIGINS: browser origins the API answers, comma-separated. Never "*".
# Empty = the dev frontend (http://localhost:3000, http://127.0.0.1:3000).
DEPLOY_ALLOWED_ORIGINS = ()

# WEBGRAPH_CHROMIUM_ARGS: extra flags for the browser, shell-split.
DEPLOY_CHROMIUM_ARGS = ""

# WEBGRAPH_CONTACT: who runs this deployment, as `Name contact@example.com`, declared to a
# site that admits automated clients only when they say who they are (sec.gov: "declare
# your traffic by updating your user agent to include company specific information"). Sent
# only to a site that asked, in the form it documents; empty = such a site is refused and
# the refusal names this setting. Never a disguise: the client is still named webgraph.
DEPLOY_CONTACT = ""
