import type { Route } from "next";

import { DOCS, REPO_ISSUES } from "@/components/site/links";

/**
 * The five products, as data. Availability is a fact about the repository today, and the
 * card's chip carries it in word and form; the description is limited to what exists (or,
 * for a coming product, to what it will be, said once and in the future tense only there).
 */
export type Availability = "available" | "coming";

export type Cta =
  | { label: string; href: Route; external?: false }
  | { label: string; href: string; external: true };

export type Product = {
  readonly id: string;
  readonly name: string;
  readonly availability: Availability;
  /** Qualifies an "available" chip -- "preview, behind a flag" -- and is left off when the
   *  plain word is the whole truth. */
  readonly note?: string;
  /** Paragraphs. Inline code is written between backticks and rendered as such. */
  readonly body: readonly string[];
  readonly ctas: readonly Cta[];
};

const NOTIFY = (product: string): Cta => ({
  label: "Notify me — GitHub issue",
  href: `${REPO_ISSUES}?title=${encodeURIComponent(`${product}: notify me`)}`,
  external: true,
});

export const PRODUCTS: readonly Product[] = [
  {
    id: "crawler",
    name: "Crawler",
    availability: "available",
    body: [
      "Every public page of a site as Markdown, in reading order, with provenance per page: " +
        "how it was fetched, whether order was measured, what was refused. A plain fetch and " +
        "a real-browser render are merged so neither side's losses are kept.",
      "It refuses walls, login pages and server errors by name, and drops what the site " +
        "hides from a reader. Streams as it goes: the live run view, or the HTTP API " +
        "(`/api/text` for a page, `/api/site/stream` for a site). Runs on your machine.",
    ],
    ctas: [
      { label: "Run a site", href: "/#start" },
      { label: "Read the docs", href: DOCS },
    ],
  },
  {
    id: "webgraph",
    name: "WebGraph",
    availability: "available",
    note: "preview, behind a flag",
    body: [
      "A model reads every extracted page and builds a knowledge graph of the site — entities " +
        "(organisations, people, courses, dates, prices, documents) and the relationships " +
        "between them — in SQLite per site, with an export and a sync to Neo4j. Nothing enters " +
        "the graph without a verbatim quote from the page that states it, and every node and " +
        "edge cites the page and block it came from.",
      "Ask the site a question and get an answer whose every sentence cites a quote, while the " +
        "path the question took lights up on the graph. Bring your own key (OpenAI-compatible, " +
        "Anthropic, Gemini) or run a local model. Off by default: start the API with " +
        "`WEBGRAPH_KG=1`.",
    ],
    ctas: [
      { label: "Open WebGraph", href: "/graph" },
      { label: "Read the docs", href: `${DOCS}/webgraph` as Route },
    ],
  },
  {
    id: "site-truth-report",
    name: "Site Truth Report",
    availability: "available",
    body: [
      "What a site shows people, what it shows machines, and how ready it is for AI agents: " +
        "words without JavaScript against words with it, what robots.txt declares for each " +
        "well-known bot, hidden and off-screen links, walls, dead links, the stack and its " +
        "age — an AI-readiness score with the evidence for every part, and a suggested " +
        "robots.txt and llms.txt. A link you can share.",
      "The crawler already found the material. On vtu.ac.in it met about 60 gambling links " +
        "on every page, each positioned twenty trillion pixels off the left edge; the " +
        "extraction drops them, and the report says they are there. It never fetches as " +
        "another bot: the bots table is what the site's file declares.",
    ],
    ctas: [
      { label: "Run a report", href: "/report" },
      { label: "Read the docs", href: DOCS },
    ],
  },
  {
    id: "watch",
    name: "Watch",
    availability: "available",
    body: [
      "Tell it a site; run it again whenever you like. Each run crawls with the previous " +
        "run's pages as seeds, compares every page by its content hash and then section by " +
        "section, and records what changed with the section heading and the page — in the " +
        "page's own words, with no model involved.",
      "Navigation, footers, comments, timestamps and visitor counters are left out before " +
        "comparing, so a bumped \"last updated\" line is not news. Changes come out as a list, " +
        "a Markdown digest or an RSS/Atom feed — a university's circulars as a feed. " +
        "`webgraph watch run` is what a cron entry or a GitHub Action calls.",
    ],
    ctas: [
      { label: "Open Watch", href: "/watch" },
      { label: "Read the docs", href: DOCS },
    ],
  },
  {
    id: "cli",
    name: "CLI",
    availability: "available",
    body: [
      "`webgraph site example.com` — analyse, enumerate and extract a whole site from the " +
        "terminal. `webgraph text <url>` for one page in reading order, `webgraph diff` and " +
        "`webgraph watch` for what changed since the last crawl, `webgraph bench` to score " +
        "the engine against a labelled corpus.",
      "The same refusals and provenance as the API: a wall is named, an assumed order says so.",
    ],
    ctas: [{ label: "Read the docs", href: DOCS }],
  },
];
