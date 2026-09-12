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
      "Every row is scored on the same cached HTML that ships with the corpus. Baselines are the authors' own published per-page scores over those same files.",
    name: "WCEB",
    pages: "3,985 pages · 8 corpora",
    metric: "ROUGE-LSum F1",
    asks: "How much of the annotated main content survives, across eight independently built corpora.",
    caveat:
      "The widest corpus here and the only one whose authors have no system in the comparison. Baselines are the authors' own published per-page scores.",
    max: 1,
    entries: [
      { name: "trafilatura", score: 0.867 },
      { name: "readability", score: 0.855 },
      { name: "webgraph", score: 0.843, self: true },
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
      "Checked directly: trafilatura run here today scores 0.911 against the 0.907 published, so the published column still describes the system it names and first place is real.",
    name: "WCEB · cetd",
    pages: "700 pages",
    metric: "ROUGE-LSum F1",
    asks: "One corpus inside WCEB, and the only board anywhere on which this engine is first.",
    caveat:
      "A single corpus of 700 pages. First place here is a real result against the published field, not a claim about the web.",
    max: 1,
    entries: [
      { name: "webgraph", score: 0.925, self: true },
      { name: "trafilatura 2.2.0", score: 0.911, note: "run here today; published figure 0.907" },
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
      "Running trafilatura through this harness today scores 0.813 against the 0.791 its paper reports \u2014 almost all of it on forum pages, where a later release learned to read Discourse threads. So the published rows describe older software, and the only pairing here measured on one scale is trafilatura 2.2.0 against this engine. It is ahead.",
    name: "WCXB",
    pages: "1,497 pages · 7 page types",
    metric: "word-level F1",
    asks: "Whether an extractor holds up away from articles, on forums, products, listings and documentation.",
    caveat:
      "The author of the top entry wrote it and tuned it on this split, and discloses so. The held-out test split has never been opened here.",
    max: 1,
    entries: [
      { name: "rs-trafilatura", score: 0.859, note: "published; author's own, tuned on this split" },
      { name: "MinerU-HTML", score: 0.827, note: "published 2026; not re-run here" },
      { name: "trafilatura 2.2.0", score: 0.813, note: "run here today, same harness" },
      { name: "webgraph", score: 0.811, self: true, note: "run here today, same harness" },
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
      { name: "webgraph", score: 0.599, self: true, note: "column mean, comparable to the published rows" },
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
      { name: "goose3", score: 0.896 },
      { name: "webgraph", score: 0.895, self: true, note: "15th of 35" },
      { name: "readability-rs", score: 0.873 },
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
  { key: "text", label: "Prose", pages: 545, us: 0.755, best: 0.862, bestName: "MinerU-HTML" },
  { key: "code", label: "Code blocks", pages: 91, us: 0.83, best: 0.909, bestName: "MinerU-HTML" },
  { key: "table", label: "Tables", pages: 157, us: 0.359, best: 0.678, bestName: "MinerU-HTML" },
  { key: "teds", label: "Table structure", pages: 157, us: 0.582, best: 0.739, bestName: "MinerU-HTML" },
  { key: "formula", label: "Equations", pages: 143, us: 0.47, best: 0.94, bestName: "MinerU-HTML" },
];

/** WCXB across this session, each step a diagnosed extraction bug rather than a tuned constant. */
export type Step = { readonly label: string; readonly score: number; readonly why: string };

export const PROGRESSION: readonly Step[] = [
  { label: "Start", score: 0.714, why: "where the session began" },
  { label: "noscript + form controls", score: 0.73, why: "19 forum pages parsed to zero blocks" },
  { label: "main landmark", score: 0.734, why: "178 pages declare main content by ARIA role alone" },
  { label: "wrapper duplication", score: 0.803, why: "a container re-emitted its own 24 paragraphs" },
  { label: "repeat grouping", score: 0.81, why: "scoring repeated cards as one unit" },
];
