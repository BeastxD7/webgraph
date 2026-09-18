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
    href: "/ui/how-scene",
    title: "How it reads a page — scene",
    description: "The isometric illustration (how/Scene.tsx) with direct step controls, an in-view toggle, and bounding-box overlays for checking centering.",
  },
  {
    href: "/ui/intro-bar",
    title: "Step 1 — intro bar",
    description: "Blank canvas → brand mark → mark dissolves into a search bar expanding from center → types → enters. Plain HTML/CSS, decoupled from the isometric scene, for iterating on timing and easing before it's ported in.",
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
