/**
 * The crawl, stage by stage, as content rather than as prose in a component.
 *
 * Kept as data so the page renders one shape per stage and cannot drift: every stage says
 * what it takes in, what it hands on, and what it does when that stage goes wrong. The
 * failure list is not an appendix -- on a crawl of thousands of pages it is most of the
 * engineering, and a walkthrough that omits it describes a demo rather than a crawler.
 *
 * Every figure here comes from a benchmark run or a diagnostic in this repository.
 */

export type Failure = { readonly when: string; readonly then: string };

export type Stage = {
  readonly id: string;
  readonly title: string;
  /** What the stage does, in a few short paragraphs. */
  readonly body: readonly string[];
  readonly takes: string;
  readonly gives: readonly string[];
  /** A point worth pulling out of the flow. */
  readonly note?: string;
  readonly failures?: readonly Failure[];
  readonly failureTitle?: string;
  /** Rescues that exist because a real page was being ruined without them. */
  readonly rescues?: ReadonlyArray<{ readonly what: string; readonly why: string }>;
};

export const STAGES: readonly Stage[] = [
  {
    id: "probe",
    title: "Look at the front door, once",
    body: [
      "The home page is fetched two ways at the same time: as plain HTTP, and through a real browser that runs the page's JavaScript. Both results are kept.",
      "In the same pass it reads the site's robots file, collects every sitemap that file advertises, and identifies the technology behind the site from 237 fingerprint rules.",
    ],
    takes: "one URL",
    gives: ["the page, both ways", "sitemap URLs", "technology profile"],
    failures: [
      { when: "Site unreachable", then: "The crawl stops here and says why. Nothing else can proceed." },
      { when: "Redirected elsewhere", then: "The new address becomes the root, and the redirect is reported rather than followed silently." },
      { when: "No sitemap published", then: "Fine. The crawl discovers pages by following links instead." },
    ],
  },
  {
    id: "frontier",
    title: "Build the queue, and clean every address going into it",
    body: [
      "Sitemap pages seed a queue. The unglamorous part matters most: four addresses differing only by a trailing slash, a fragment, and a tracking parameter are one page. A crawler that treats them as four spends its budget four times and puts four copies of every fact in your graph.",
      "So it strips about two dozen tracking parameters, normalises ports and index filenames, and skips addresses that are clearly not pages. PDFs are deliberately kept, because a PDF is a document worth reading.",
    ],
    takes: "sitemap URLs",
    gives: ["a de-duplicated queue"],
  },
  {
    id: "loop",
    title: "Crawl and extract at the same time",
    body: [
      "Discovery and extraction are interleaved, not sequential. Pages are taken from the queue in batches, and every page that comes back has its links read and added to the queue.",
      "So the crawl reaches everything reachable rather than only what the sitemap listed, and the first result arrives in seconds instead of after a full enumeration.",
      "Once a page's links have been read, its raw markup is discarded. On a long article that markup is the single largest thing in memory and nothing needs it again.",
    ],
    takes: "the queue",
    gives: ["one result event per page, as it finishes"],
    failures: [
      { when: "A page fails", then: "Recorded against that page. The crawl carries on. One bad page never stops a run." },
      { when: "Budget reached", then: "Stops cleanly at the page limit you set, or runs until the queue empties if you set none." },
    ],
  },
  {
    id: "fetch",
    title: "Fetch each page, and keep both answers",
    body: [
      "This is the decision nothing else in the field makes. Every other engine picks one: plain HTTP, or a browser. This one takes both and merges them, because measuring 24 real sites showed two things are true at once.",
      "You cannot predict what a plain fetch will miss. Angular's own site loses 32% of its content without a browser, and a page holding 2,078 characters gives no hint that 969 more appear after its scripts run.",
      "And a browser is not a strict upgrade. The BBC gives 19,908 characters over plain HTTP and only 9,279 through a browser, because a consent wall replaces the article. Choosing the browser would have thrown away half the page.",
    ],
    takes: "one URL",
    gives: ["both representations, merged", "how much each side contributed"],
    note: "So it refuses to choose. Both representations are obtained and merged, and the result reports what each side contributed, which makes “nothing was lost” a measurement rather than a promise.",
    failures: [
      { when: "404 or 410", then: "The only fatal statuses. The page is dropped without rendering, because a browser renders a “not found” page perfectly happily and it would be extracted as though it were an article." },
      { when: "403 refused", then: "Not fatal. It escalates to the real browser, which recovers 55% of refusals — not by imitating a browser, but by being one." },
      { when: "429 or 503", then: "Means “later”, not “no”. One retry, honouring the wait the server asked for, capped at five seconds. One, because a crawler that retries hard on a 429 is the reason it was sent." },
      { when: "Browser unavailable", then: "Falls back to the plain fetch and records that rendering did not happen, so a result is never silently weaker than it claims to be." },
      { when: "An age gate or region picker", then: "The browser tries to open it, because a page stuck behind an interstitial never mounts its content at all." },
    ],
  },
  {
    id: "blocks",
    title: "Turn markup into blocks",
    body: [
      "The page becomes a list of typed blocks — paragraph, heading, list item, table, code, quote, image — one per innermost element that actually holds text.",
      "Several rescues run before anything is discarded. Each exists because a real page was being ruined without it.",
    ],
    takes: "one page's markup",
    gives: ["typed blocks, each knowing its region"],
    rescues: [
      {
        what: "Forum threads hidden from crawlers",
        why: "Discourse serves an empty shell and puts the whole thread in a fallback block that is normally thrown away. 19 of 112 forum pages produced nothing at all before this.",
      },
      {
        what: "Equations",
        why: "Mathematical markup is converted to LaTeX before anything can strip it. It used to be deleted outright, which on a scientific page removes the very thing the page is about.",
      },
      {
        what: "Dropdowns and form controls",
        why: "A 200-country selector is 400 unlinked words and beats a real article on any density measure. On one page the engine returned the country list instead of the terms and conditions.",
      },
      {
        what: "Tables",
        why: "A real data table keeps its grid, merged cells and all. A table with one row, one column, or mostly empty cells is page furniture wearing table markup, and is read as ordinary content instead.",
      },
    ],
  },
  {
    id: "order",
    title: "Put the blocks in reading order",
    body: [
      "Source order is not reading order. Any page using CSS to rearrange its layout hands you its content in the wrong sequence, and you cannot tell from the text alone.",
      "So when the browser rendered the page, the engine also recorded where every block physically sat, and reconstructs the order a person reads in by repeatedly splitting the page into columns and rows. Blocks with no measurable position — a collapsed panel, anything behind a disclosure — are placed next to their neighbours.",
    ],
    takes: "blocks, plus their measured positions",
    gives: ["blocks in the order a person reads them"],
    note: "It always says which it did: measured order, measured with some blocks anchored, or plain source order when there was no browser. A consumer is told the confidence rather than left to assume it.",
  },
  {
    id: "chrome",
    title: "Learn what the site repeats",
    body: [
      "Once six or more pages are in, the engine compares them and finds the blocks that appear on all of them. That is the site's furniture: its header, its footer, its cookie notice, its sidebar. No single page can reveal this; it only shows up across a site.",
      "A guard refuses to call more than half of any page furniture. On a documentation site where every page genuinely resembles its neighbours, that rule is the difference between removing the navigation and removing the documentation.",
    ],
    takes: "six or more extracted pages",
    gives: ["the blocks this site repeats everywhere"],
  },
  {
    id: "content",
    title: "Decide what counts as the content",
    body: [
      "Four steps, in order. Drop what the page itself labels navigation and footer. Narrow to the main region when the page declares a trustworthy one. Remove the site furniture learned in the previous stage. Then draw a boundary around the real content.",
    ],
    takes: "one page's blocks",
    gives: ["the content view", "which steps fired"],
    note: "This never destroys anything. The complete block list stays complete, and “the content” is a separate, narrower view computed from it — so the full page and the article are both available, and the reduction is always reversible.",
  },
  {
    id: "output",
    title: "Hand it back",
    body: [
      "Per page: clean text, structure-preserving Markdown, the typed blocks, the page type, and which reduction steps fired.",
      "Per site: the page graph, the links between pages, and any structured facts the pages declared about themselves.",
    ],
    takes: "every extracted page",
    gives: ["text and Markdown", "the page graph", "structured facts"],
    failureTitle: "One last check across the whole crawl",
    failures: [
      {
        when: "Three or more pages identical",
        then: "A warning. If many different addresses return the same text, the crawl is not extracting a site — it is extracting one gate, over and over. Two identical pages is a coincidence; three is a pattern.",
      },
    ],
  },
];

export const PRINCIPLES: ReadonlyArray<{ title: string; body: string }> = [
  {
    title: "Lose nothing first, narrow afterwards",
    body: "Every stage that removes something produces a new view rather than editing the original. That is why a mistake in content selection costs you a worse summary and never costs you the page.",
  },
  {
    title: "A failure is a recorded fact, not an exception",
    body: "An unreachable host, a refused page, a browser that would not start — each becomes a value attached to that page while the crawl continues. Across thousands of pages, anything else means one bad page ends the run.",
  },
];
