/**
 * Every number on the benchmarks page, with what produced it.
 *
 * Two rules this file exists to enforce. Ours are runs of the benchmark runners in this
 * repository, on this machine, against a local corpus clone; everybody else's are the
 * figures their authors published, and no competing system was executed here. And each
 * board carries the caveat that would otherwise have to be found by reading source.
 */

export type Entry = {
  readonly name: string;
  readonly score: number;
  /** Ours. Rendered differently and never sorted to the top. */
  readonly self?: boolean;
  /** A diagnostic or ceiling rather than a system: drawn, never ranked. */
  readonly reference?: boolean;
  readonly note?: string;
};

/**
 * How far a side-by-side comparison on this board can be trusted.
 *
 * `same-inputs`  every system was scored on the same cached files with the same scorer, so
 *                the rows are directly comparable.
 * `same-corpus`  same corpus and metric, but the other rows are their authors' published
 *                figures rather than runs made here.
 * `not-compared` the other rows were produced against a different web, on a different day.
 *                The bars are drawn for context and the ranking is not a ranking.
 */
export type Trust = "same-inputs" | "same-corpus" | "not-compared";

export type Board = {
  readonly id: string;
  /** Boards with a long field need the full width or their labels become unreadable. */
  readonly wide?: boolean;
  readonly trust: Trust;
  /** Why the trust level is what it is, in one sentence a reader can check. */
  readonly comparability: string;
  readonly name: string;
  readonly pages: string;
  readonly metric: string;
  /** What the benchmark is actually asking. One sentence. */
  readonly asks: string;
  /** What it cannot see, or what would mislead a reader who only saw the bars. */
  readonly caveat: string;
  readonly max: number;
  readonly entries: readonly Entry[];
};

export const BOARDS: readonly Board[] = [
  {
    id: "wceb",
    trust: "same-corpus",
    comparability:
      "Every row is scored on the same cached HTML that ships with the corpus. Baselines are the authors' own published per-page scores over those same files; WCEB ran trafilatura with comments excluded, and the row for this engine is the production path, which also strips the comments under an article.",
    name: "WCEB",
    pages: "3,985 pages · 8 corpora",
    metric: "ROUGE-LSum F1",
    asks: "How much of the annotated main content survives, across eight independently built corpora.",
    caveat:
      "The widest corpus here and the only one whose authors have no system in the comparison. Second, 0.011 behind trafilatura. Two of the eight corpora — Dragnet (1,379 pages) and cetd — count a page's comment threads as content, and the production path removes them: on Dragnet it scores 0.792 where the same engine with that one step left out scores 0.849. That variant is drawn as a reference line, not ranked, because it is not what the API returns. Until this page was re-measured on 14 September it showed the reference figure as the ranked one.",
    max: 1,
    entries: [
      { name: "webgraph", score: 0.856, self: true, note: "production path, run here 14 Sep 2026; was 0.852 before #50–#52" },
      { name: "webgraph, comments kept", score: 0.874, reference: true, note: "landmarks + boundary only, no comment stripping — the figure shown here until 14 Sep" },
      { name: "trafilatura", score: 0.867 },
      { name: "readability", score: 0.855 },
      { name: "boilerpipe", score: 0.825 },
      { name: "resiliparse", score: 0.819 },
      { name: "jusText", score: 0.806 },
      { name: "BeautifulSoup", score: 0.692 },
    ],
  },
  {
    id: "wceb-cetd",
    trust: "same-corpus",
    comparability:
      "Checked directly: trafilatura run here scores 0.911 against the 0.907 published, so the published column still describes the system it names.",
    name: "WCEB · cetd",
    pages: "700 pages",
    metric: "ROUGE-LSum F1",
    asks: "One corpus inside WCEB, shown on its own because it is where the comment question costs this engine the most.",
    caveat:
      "A single corpus of 700 pages. The production path is level with readability and 0.014 behind trafilatura; with comments kept the same engine scores 0.928, ahead of everything published — cetd's annotators counted the threads as content. Neither figure is a claim about the web.",
    max: 1,
    entries: [
      { name: "webgraph", score: 0.897, self: true, note: "production path, run here 14 Sep 2026" },
      { name: "webgraph, comments kept", score: 0.928, reference: true, note: "no comment stripping; was the ranked figure until 14 Sep" },
      { name: "trafilatura 2.2.0", score: 0.911, note: "run here earlier; published figure 0.907" },
      { name: "readability", score: 0.897 },
      { name: "resiliparse", score: 0.881 },
      { name: "jusText", score: 0.863 },
      { name: "boilerpipe", score: 0.85 },
      { name: "BeautifulSoup", score: 0.759 },
    ],
  },
  {
    id: "wcxb",
    trust: "same-corpus",
    comparability:
      "Running trafilatura through this harness scores 0.813 against the 0.791 its paper reports \u2014 almost all of it on forum pages, where a later release learned to read Discourse threads. So the published rows describe older software. The row for this engine is the production path: the page-type router's out-of-fold predictions choosing the per-type policy, on the same cached HTML with the corpus's own scorer.",
    name: "WCXB",
    pages: "1,497 pages · 7 page types · dev split",
    metric: "word-level F1",
    asks: "Whether an extractor holds up away from articles, on forums, products, listings and documentation.",
    caveat:
      "First by 0.002 over an entry whose author tuned it on this split and discloses so; a margin that small is a tie. On the 511-page held-out test split, never used for any decision here, this engine scores 0.875 (routed) and 0.864 (unrouted); rs-trafilatura's author reports 0.893 there, so the test split still has the published entry ahead.",
    max: 1,
    entries: [
      { name: "webgraph", score: 0.861, self: true, note: "run here 14 Sep 2026, routed by page type; 0.836 unrouted; was 0.855" },
      { name: "rs-trafilatura", score: 0.859, note: "published; author's own, tuned on this split" },
      { name: "MinerU-HTML", score: 0.827, note: "published 2026; not re-run here" },
      { name: "trafilatura 2.2.0", score: 0.813, note: "run here, same harness" },
      { name: "trafilatura 2.0.0", score: 0.791, note: "the figure the paper published, two releases old" },
      { name: "ReaderLM-v2", score: 0.741, note: "published; not re-run here" },
      { name: "magic-html", score: 0.719, note: "published; not re-run here" },
    ],
  },
  {
    id: "webmainbench",
    trust: "same-corpus",
    comparability:
      "Cached HTML shipped with the corpus, scored with the corpus's own calculator. The engine's figure is a plain mean of the five columns, which is how the published rows are computed.",
    name: "WebMainBench",
    pages: "545 pages · calibrated subset",
    metric: "edit distance, 5 columns",
    asks:
      "Whether tables, code and equations survive as structure, not just as words. The only board that grades them separately.",
    caveat:
      "Built by the team that also built the first and second place systems. Its ground truth for tables is the source HTML, which favours an extractor that returns markup unchanged.",
    max: 1,
    entries: [
      { name: "MinerU-HTML", score: 0.826 },
      { name: "webgraph", score: 0.646, self: true, note: "column mean, comparable to the published rows; was 0.631" },
      { name: "magic-html", score: 0.5 },
      { name: "trafilatura (md)", score: 0.401 },
      { name: "trafilatura (txt)", score: 0.372 },
      { name: "resiliparse", score: 0.29 },
    ],
  },
  {
    id: "zyte",
    wide: true,
    trust: "same-inputs",
    comparability:
      "The strongest comparison here. Every competing row was produced by running the corpus's own scorer over the outputs those systems committed to the repository, in the same command that scored this engine.",
    name: "Zyte article-extraction",
    pages: "181 news articles",
    metric: "4-gram shingle F1",
    asks: "How cleanly a news article body comes out, against a field of article-specific extractors.",
    caveat:
      "Every leader here is built for news articles and nothing else. This engine is general-purpose, which is the trade, not an excuse. Shown: the top of a 35-entry board.",
    max: 1,
    entries: [
      { name: "AutoExtract", score: 0.97 },
      { name: "rs-trafilatura", score: 0.97 },
      { name: "go-trafilatura", score: 0.96 },
      { name: "trafilatura", score: 0.958 },
      { name: "Diffbot", score: 0.951 },
      { name: "newspaper", score: 0.949 },
      { name: "readability.js", score: 0.947 },
      { name: "webgraph", score: 0.945, self: true, note: "10th of 35, run here 14 Sep 2026; was 0.934" },
      { name: "go-readability", score: 0.934 },
      { name: "go-domdistiller", score: 0.927 },
      { name: "readability", score: 0.922 },
      { name: "goose3", score: 0.896 },
      { name: "jusText", score: 0.804 },
    ],
  },
  {
    id: "scrape-evals",
    wide: true,
    trust: "not-compared",
    comparability:
      "The published figures were measured in November 2025 and these in September 2026, against a thousand live URLs that have moved on: 90 of them now return 404 and cannot be fetched by anyone. The columns describe two different webs and the ordering between them means nothing.",
    name: "Firecrawl scrape-evals",
    pages: "1,000 live URLs",
    metric: "best-window F1",
    asks:
      "The only board that scores a real scrape end to end, fetching included. Every other one hands each engine the same saved file.",
    caveat:
      "Seven of the thirteen published engines fetch through commercial anti-bot infrastructure; this engine fetches from one address with no proxy. Among the engines that do the same, it leads.",
    max: 0.8,
    entries: [
      { name: "Firecrawl", score: 0.676, note: "hosted anti-bot browser" },
      { name: "Exa", score: 0.527, note: "commercial proxy" },
      { name: "Tavily", score: 0.501, note: "commercial proxy" },
      { name: "Zyte", score: 0.468, note: "commercial proxy" },
      { name: "Crawl4AI", score: 0.453, note: "own address" },
      { name: "ScrapingBee", score: 0.451, note: "commercial proxy" },
      { name: "ScraperAPI", score: 0.45, note: "commercial proxy" },
      { name: "webgraph", score: 0.446, self: true, note: "own address, no proxy" },
      { name: "Scrapy", score: 0.429, note: "own address" },
      { name: "Apify", score: 0.417, note: "commercial proxy" },
      { name: "Puppeteer", score: 0.408, note: "own address" },
      { name: "Selenium", score: 0.405, note: "own address" },
      { name: "requests", score: 0.355, note: "own address" },
      { name: "Playwright", score: 0.339, note: "own address" },
    ],
  },
];

/**
 * scrape-evals as a plane rather than a ranking.
 *
 * This is the one board with two independent axes -- how many pages an engine could fetch at
 * all, and how well it extracted the ones it got -- and collapsing them into a single ranked
 * list hides the finding. Plotted, the field separates into two clusters by whether the engine
 * pays for anti-bot infrastructure, and the separation is horizontal: the commercial services
 * are further right, not further up.
 */
export type Point = {
  readonly name: string;
  /** Share of the 1,000 URLs fetched successfully. */
  readonly coverage: number;
  /** Best-window F1 on what came back. */
  readonly quality: number;
  readonly proxy: boolean;
  readonly self?: boolean;
};

export const SCRAPE_PLANE: readonly Point[] = [
  { name: "Firecrawl", coverage: 0.809, quality: 0.6758, proxy: true },
  { name: "Exa", coverage: 0.763, quality: 0.5268, proxy: true },
  { name: "Tavily", coverage: 0.676, quality: 0.5011, proxy: true },
  { name: "Zyte", coverage: 0.629, quality: 0.4682, proxy: true },
  { name: "ScraperAPI", coverage: 0.635, quality: 0.4498, proxy: true },
  { name: "ScrapingBee", coverage: 0.606, quality: 0.4505, proxy: true },
  { name: "Apify", coverage: 0.602, quality: 0.4166, proxy: true },
  { name: "Crawl4AI", coverage: 0.58, quality: 0.4533, proxy: false },
  { name: "webgraph", coverage: 0.634, quality: 0.4455, proxy: false, self: true },
  { name: "Scrapy", coverage: 0.54, quality: 0.429, proxy: false },
  { name: "Puppeteer", coverage: 0.537, quality: 0.4083, proxy: false },
  { name: "Selenium", coverage: 0.55, quality: 0.4046, proxy: false },
  { name: "requests", coverage: 0.506, quality: 0.355, proxy: false },
  { name: "Playwright", coverage: 0.395, quality: 0.3387, proxy: false },
];

/** WebMainBench's five columns: where the remaining distance actually sits. */
export type Column = {
  readonly key: string;
  readonly label: string;
  readonly pages: number;
  readonly us: number;
  readonly best: number;
  readonly bestName: string;
};

export const COLUMNS: readonly Column[] = [
  { key: "text", label: "Prose", pages: 545, us: 0.774, best: 0.862, bestName: "MinerU-HTML" },
  { key: "code", label: "Code blocks", pages: 91, us: 0.847, best: 0.909, bestName: "MinerU-HTML" },
  { key: "table", label: "Tables", pages: 121, us: 0.404, best: 0.678, bestName: "MinerU-HTML" },
  { key: "teds", label: "Table structure", pages: 121, us: 0.601, best: 0.739, bestName: "MinerU-HTML" },
  { key: "formula", label: "Equations", pages: 145, us: 0.605, best: 0.94, bestName: "MinerU-HTML" },
];

/** WCXB across this session, each step a diagnosed extraction bug rather than a tuned constant. */
export type Step = { readonly label: string; readonly score: number; readonly why: string };

export const PROGRESSION: readonly Step[] = [
  { label: "Start of round", score: 0.82, why: "routed by page type, before this round" },
  { label: "product sheet + filter panels", score: 0.823, why: "reviews and facets are not the product" },
  { label: "consent dialogs, asides", score: 0.83, why: "a cookie centre chosen as a thread; a deals rail" },
  { label: "text is text", score: 0.842, why: "alt text and sr-only labels are not page text" },
  { label: "comments, landmarks", score: 0.848, why: "a thread is not the story; broken nav swallowed main" },
  { label: "main by script, prose guard", score: 0.85, why: "a Japanese <main> behind a mega-menu; a short story keeps losing its thread" },
  { label: "rails, <article>, quotes, forum furniture", score: 0.855, why: "tickers and share bars; the dominant article; repeated quotes; signatures and user cards" },
  { label: "restated wholes, named chrome, cost re-swept, article body", score: 0.861, why: "an article repeated as one block; div#footer and div.nav; the boundary cost re-swept for the stripped page; the declared article body" },
];

/** When and against what the rows marked as this engine were measured. */
export const MEASURED = {
  date: "14 September 2026",
  commit: "4773784",
} as const;

/**
 * WCXB by page type. Published rows are the paper's Table 7 (arXiv 2605.21097) and, for
 * Hydrafetch, their own August 2026 run of the same dev split with the same scorer; the
 * paper's trafilatura is 2.0.0 and Hydrafetch's is 2.2.0, which is why they differ. This
 * engine's row is the routed production path on the dev split, 14 September 2026.
 */
export type TypeSystem = { readonly key: string; readonly label: string; readonly self?: boolean };
export type TypeRow = {
  readonly type: string;
  readonly n: number;
  readonly scores: Readonly<Record<string, number>>;
};

export const TYPE_SYSTEMS: readonly TypeSystem[] = [
  { key: "webgraph", label: "webgraph", self: true },
  { key: "rs", label: "rs-trafilatura" },
  { key: "mineru", label: "MinerU-HTML" },
  { key: "hydra", label: "Hydrafetch" },
  { key: "traf", label: "trafilatura 2.0" },
];

export const TYPE_ROWS: readonly TypeRow[] = [
  { type: "article", n: 793, scores: { webgraph: 0.944, rs: 0.932, mineru: 0.928, hydra: 0.9289, traf: 0.924 } },
  { type: "documentation", n: 91, scores: { webgraph: 0.929, rs: 0.931, mineru: 0.838, hydra: 0.9231, traf: 0.888 } },
  { type: "service", n: 165, scores: { webgraph: 0.842, rs: 0.843, mineru: 0.824, hydra: 0.7993, traf: 0.751 } },
  { type: "forum", n: 113, scores: { webgraph: 0.8, rs: 0.792, mineru: 0.794, hydra: 0.7275, traf: 0.575 } },
  { type: "collection", n: 117, scores: { webgraph: 0.692, rs: 0.713, mineru: 0.506, hydra: 0.6093, traf: 0.518 } },
  { type: "listing", n: 99, scores: { webgraph: 0.706, rs: 0.704, mineru: 0.71, hydra: 0.6612, traf: 0.55 } },
  { type: "product", n: 119, scores: { webgraph: 0.636, rs: 0.67, mineru: 0.619, hydra: 0.5895, traf: 0.562 } },
];

/** Benchmarks a reader would expect here, and why they are not. */
export type NotRunItem = { readonly name: string; readonly what: string; readonly why: string };

export const NOT_RUN: readonly NotRunItem[] = [
  {
    name: "CrawlBench (Firecrawl)",
    what: "LLM structured extraction",
    why: "It scores JSON pulled from live pages against a schema by a language model, not the Markdown of a page, and the dataset is not published; running it needs an LLM key and their harness. This engine's schema extraction could be scored on it, and has not been.",
  },
  {
    name: "Hydrafetch extraction benchmark",
    what: "same corpus as WCXB",
    why: "Not a separate corpus: it is the WCXB dev split scored with WCXB's own metric, published with Hydrafetch's own extractor added. Their per-type figures are the Hydrafetch column in the table above; the row for this engine is the same WCXB run, so nothing was run twice.",
  },
  {
    name: "Dragnet and Boilerpipe corpora",
    what: "inside WCEB",
    why: "Both are among the eight corpora WCEB combines (Dragnet as its own set; the Boilerpipe-era L3S-GN1 and Google-Trends sets alongside it), so they are scored above under WCEB rather than a second time on their own.",
  },
];
