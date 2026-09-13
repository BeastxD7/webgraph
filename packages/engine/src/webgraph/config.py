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

# Open <details> and ARIA disclosure panels before measuring. Off until measured.
RENDER_REVEAL_COLLAPSED = False

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

# ======================================================================================
# Resolving a page (deciding what came back)
# ======================================================================================

# Statuses meaning the page does not exist. Never rendered -- a browser renders a 404 page
# perfectly happily and reports "Not Found" as content.
MISSING_STATUSES = frozenset({404, 410})

# Statuses that mean something a person can act on, said in words.
BLOCKING_STATUSES = {
    401: "the page requires a sign-in",
    403: "the site refused this client",
    429: "the site is rate-limiting this client",
    451: "the page is blocked for legal reasons",
    503: "the site said it was too busy, which is also how several of them refuse bots",
}

# A page shorter than this that says what walls say ("you've been blocked", "verify you
# are human") is refused as a block page. Longer pages merely mentioning those words are
# pages.
MAX_BLOCK_PAGE_CHARS = 1_500

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
CONTENT_COST_RATIO = 0.70  # cost = clamp(ratio * mean block words, floor, ceiling)
CONTENT_COST_FLOOR = 5.0
CONTENT_COST_CEILING = 18.0
CONTENT_BLOCK_COST = 13.0  # the fixed cost, when CONTENT_ADAPTIVE_COST is False

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
# The comments under a page are stripped only when at least this many words remain outside
# them -- a story with a thread beneath it. Below it the comments are the page (a Hacker
# News comment page, a GitHub issue) and stay whatever the page type.
CHROME_MIN_COMMENT_HOST_WORDS = 250
# A <main> landmark is trusted only if it holds at least this many words and this share
# of the page; otherwise it is decoration and ignored.
CHROME_MAIN_MIN_WORDS = 100
CHROME_MAIN_MIN_SHARE = 0.5

# ======================================================================================
# Page type (the router)
# ======================================================================================

# Below this confidence the router says "unknown" and the default policy applies. Out of
# fold it is right 86% of the time above 0.5 and 44% below.
ROUTER_MIN_CONFIDENCE = 0.5

# ======================================================================================
# Crawling a whole site
# ======================================================================================

# Pages to extract. 0 = unbounded, until the frontier is exhausted.
CRAWL_MAX_PAGES = 0

# Pages fetched in parallel within one crawl.
CRAWL_CONCURRENCY = 4

# Pause between fetches per worker, in seconds.
CRAWL_DELAY_SECONDS = 0.3

# How many links away from the root the crawl goes. 0 = the root alone; 1 = the root and
# everything it links to; and so on. The crawl is breadth-first: every page at depth n is
# fetched before any page at depth n+1.
CRAWL_MAX_DEPTH = 12

# True: stay on the root's host (www.example.com and example.com are one host).
# False: also follow subdomains (blog.example.com, shop.example.com). Never other sites.
CRAWL_STRICT_DOMAIN = True

# Check each sitemap URL with a cheap request before spending a page on it.
CRAWL_VERIFY_INVENTORY = True

# Discover pages by following links, as well as by reading the sitemap.
CRAWL_FOLLOW_LINKS = True

# URLs harvested by link-following before verification.
CRAWL_DISCOVERY_LIMIT = 400

# URLs read from sitemaps, at most.
CRAWL_SITEMAP_LIMIT = 50_000

# Honour robots.txt.
CRAWL_RESPECT_ROBOTS = True

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
# Technology profiling
# ======================================================================================

# Script bundles fetched to fingerprint frameworks, and the total bytes read.
PROFILE_MAX_SCRIPTS = 4
PROFILE_MAX_TOTAL_BYTES = 3_000_000

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

# WEBGRAPH_ALLOWED_ORIGINS: browser origins the API answers, comma-separated. Never "*".
# Empty = the dev frontend (http://localhost:3000, http://127.0.0.1:3000).
DEPLOY_ALLOWED_ORIGINS = ()

# WEBGRAPH_CHROMIUM_ARGS: extra flags for the browser, shell-split.
DEPLOY_CHROMIUM_ARGS = ""
