import type { Route } from "next";

import { DOCS, REPO_ISSUES } from "@/components/site/links";

/**
 * The four products, as data. Availability is a fact about the repository today, and the
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
    availability: "coming",
    body: [
      "An LLM reads every extracted page and builds a knowledge graph of the site — entities " +
        "(organisations, people, courses, dates, prices, documents) and the relationships " +
        "between them — stored in a graph database, every node and edge citing the page and " +
        "block it came from.",
      "Ask the site a question and get a cited answer; export the graph to your own tools. " +
        "Bring your own model key or run a local model.",
    ],
    ctas: [NOTIFY("WebGraph")],
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
    id: "cli",
    name: "CLI",
    availability: "available",
    body: [
      "`webgraph site example.com` — analyse, enumerate and extract a whole site from the " +
        "terminal. `webgraph text <url>` for one page in reading order, `webgraph diff` for " +
        "what changed since the last crawl, `webgraph bench` to score the engine against a " +
        "labelled corpus.",
      "The same refusals and provenance as the API: a wall is named, an assumed order says so.",
    ],
    ctas: [{ label: "Read the docs", href: DOCS }],
  },
];
