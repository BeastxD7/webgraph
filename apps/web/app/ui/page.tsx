import Link from "next/link";

import type { Metadata, Route } from "next";

export const metadata: Metadata = { title: "UI playground", robots: { index: false, follow: false } };

/**
 * A dev-only preview library: each entry renders a real landing component in isolation, with
 * direct controls over the states that are normally scroll- or click-driven, so a component
 * can be iterated on and checked (sizing, centering, per-state look) without scrolling the
 * real page into position every time. Not linked from the site; reached by URL only. Add an
 * entry here for each component worth previewing this way as the library grows.
 */
const ENTRIES: ReadonlyArray<{ href: Route; title: string; description: string }> = [
  {
    href: "/ui/fetch-twice",
    title: "Step 2 — fetch twice",
    description: "A page from the crawl fetched two ways at once: raw HTML streaming on the left, a browser painting (then losing a block to hydration, gaining one from a script) on the right, and the union the engine keeps.",
  },
  {
    href: "/ui/refuse-walls",
    title: "Step 3 — refuse the walls, drop the hidden",
    description: "A login redirect, a 503 and a bot challenge each stamped REFUSED; then the real page, with its cookie banner, off-screen links and display:none block surfaced and dropped.",
  },
  {
    href: "/ui/reading-order",
    title: "Step 4 — reading order, then Markdown",
    description: "The page's boxes with the recursive XY-cut drawn over them, numbers landing in reading order (the sidebar reads fifth), and the Markdown writing itself in that order under a header that says how it was fetched.",
  },
  {
    href: "/ui/build-graph",
    title: "Step 5 — build the graph",
    description: "Pages settle as nodes with their structure between them, the links they carry draw across the tree, sections hang off pages, and an entity with its schema.org identity gathers an edge from every page that names it.",
  },
  {
    href: "/ui/intro-bar",
    title: "Step 1 — intro bar",
    description: "Blank canvas → brand mark → mark dissolves into a search bar expanding from center → types → enters. Plain HTML/CSS, for iterating on timing and easing; the landing page runs its own copy (how/Step1Intro.tsx).",
  },
];

export default function UiIndex() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <p className="font-mono text-caption uppercase tracking-wide text-muted">UI playground</p>
      <h1 className="mt-2 text-h2 font-bold text-ink">Component previews</h1>
      <p className="mt-3 max-w-prose text-body text-muted">
        Each of these renders a real component from the landing page in isolation, with the
        states it normally only reaches via scroll or a click exposed as direct controls.
        Not linked anywhere on the site.
      </p>
      <ul className="mt-10 flex flex-col gap-4">
        {ENTRIES.map((e) => (
          <li key={e.href}>
            <Link
              href={e.href}
              className="block rounded-xl border border-rule bg-surface p-5 transition-colors hover:border-rule-strong"
            >
              <span className="text-h3 font-bold text-ink">{e.title}</span>
              <p className="mt-1 text-small text-muted">{e.description}</p>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
