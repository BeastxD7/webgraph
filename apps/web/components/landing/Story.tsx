import type { CSSProperties } from "react";

import Link from "next/link";

import { FIDELITY, RENDER_PREDICTION } from "@/lib/benchmarks";

import "./how/how.css";

import HowMotion from "./how/HowMotion";

/**
 * Chapters one to five -- how it reads a page -- as a full-width scroll story
 * (`how/HowMotion.tsx`): five flat, looping illustrations (`how/Step1Intro.tsx` ...
 * `Step5Graph.tsx`) pin beside a curved path of five numbered stops while scroll progress,
 * smoothed by a spring, steps through discovery, fetch, refuse the walls, read in order,
 * then build the graph. Below it, three cards, each holding a small piece of the product's real
 * output. The intro copy and the cards keep the page's usual column width; only the scroll
 * stage itself runs full-bleed. The behaviour is an enhancement: without JavaScript, or
 * under reduced motion, all five steps render stacked and unpinned (`how/HowMotion.tsx`'s
 * `.how-static` branch).
 *
 * Every figure is read from `lib/benchmarks.ts`; every example is one the changelog
 * records; every message on the cards is quoted from the engine.
 */
const STEPS: ReadonlyArray<{ title: string; body: string }> = [
  {
    title: "Discover the pages",
    body:
      "Every crawl starts by finding out what's actually there: robots.txt, then " +
      "sitemap.xml, then the links each page turns up. A queue, not a guess. On one " +
      "university site that queue held 17,000 URLs, a third of them PDFs, counted but " +
      "never fetched.",
  },
  {
    title: "Fetch twice",
    body:
      "A plain request and a real Chromium render, 1440×900. Neither alone is complete: " +
      "rendering loses server markup on hydration; a plain fetch misses what scripts insert. " +
      `Predicting which a page needs scored ${RENDER_PREDICTION.hit} of ${RENDER_PREDICTION.of}, ` +
      "so the engine stopped predicting and reads both.",
  },
  {
    title: "Refuse the walls, drop the hidden",
    body:
      "A wall is not a page. A login redirect, a bot challenge, a 503 are refused in the " +
      "engine's own words, never passed off as the page. What the browser hides stays hidden: " +
      "cookie banners, closed dialogs, links parked off the screen, display:none. On one " +
      "university site that was ~60 gambling links on every page; on one government site, " +
      "2,100 words in nine closed dialogs.",
  },
  {
    title: "Reading order, then Markdown",
    body:
      "Every element is measured. Reading order is a recursive XY-cut over the boxes, so " +
      "columns stay columns. The Markdown says whether its order was measured or assumed, " +
      "how the page was fetched and what was refused. The Site Truth Report says the same " +
      "for a whole site.",
  },
  {
    title: "Build the graph",
    body:
      "Pages, sections and the links between them become a graph: the site already is one, " +
      "nothing here is LLM-inferred. Entities carry their schema.org identity across every " +
      "page that mentions them.",
  },
];

const REFUSALS = [
  ["login wall", "redirected to a login page (/accounts/login?next=…); the page requires a sign-in"],
  ["HTTP 503", "HTTP 503 -- the site said it was too busy, which is also how several of them refuse bots"],
  ["robots.txt", "robots.txt disallows /search for this client (`User-agent: *` / `Disallow: /search`)"],
] as const;

/** Real anchors: `Citation.anchor` is `url#xpath`, read from docs.python.org on 17 Sep 2026. */
const PROVENANCE = [
  ["docs.python.org/3/tutorial/#/html/body/div[3]/div[1]/div/div/section/p[1]", "Python is an easy to learn, powerful programming language."],
  ["…/tutorial/#…/section/p[2]", "The Python interpreter and the extensive standard library are freely available…"],
  ["…/tutorial/#…/section/p[7]", "The Glossary is also worth going through."],
] as const;

const idx = (i: number) => ({ "--i": i }) as CSSProperties;

export default function Story() {
  return (
    <section aria-labelledby="how-title" className="max-md:pt-14 md:pt-24">
      <div className="page-col">
        <div className="mx-auto max-w-3xl text-center">
          <p className="how-eyebrow" data-reveal>
            How it reads a page
          </p>
          <h2 id="how-title" className="how-title mt-5" data-reveal style={idx(1)}>
            Reads the page the way a <em>person</em> does.
          </h2>
          <p className="measure-lede mx-auto mt-5 text-body text-muted" data-reveal style={idx(2)}>
            Point a naive reader at a website and it returns the cookie banner as the article, a
            login page as the page, a 503 as text, sixty links no reader ever saw. This engine
            fetches twice, refuses the walls, drops what the browser hides, and writes the page
            in the order a reader sees it.
          </p>
        </div>
      </div>

      {/* The scroll story: full-bleed, not boxed in the page column. */}
      <div className="mt-12 md:mt-16" data-reveal style={idx(3)}>
        <HowMotion steps={STEPS} />
        <p className="how-outro">
          Stay on any step as long as you like — the illustration keeps moving; it never
          freezes waiting for you to scroll on.
        </p>
      </div>

      <div className="page-col">
        {/* Three cards, each holding a piece of the real output. */}
        <div className="how-cards mt-6 grid gap-4 md:grid-cols-3">
          <article className="how-card" data-reveal style={idx(0)}>
            <h3 className="text-h3 font-bold text-ink">Fidelity, measured</h3>
            <p className="mt-2 text-small text-muted">
              Whole-page word recall against Chromium&rsquo;s own innerText, on {FIDELITY.sites}{" "}
              sites: 1.000 on {FIDELITY.perfect}, nothing below {FIDELITY.floor}.
            </p>
            <div className="mock mock-recall" aria-hidden>
              <div className="mock-ui">
                <div className="mock-head">
                  <span className="dot" />
                  <span>fidelity · sqlite.org/lang.html</span>
                </div>
                <div className="mock-body">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-small font-semibold text-ink">Word recall</span>
                    <span className="chip chip-good">measured</span>
                  </div>
                  <p className="tabular mt-2 font-display text-stat text-ink" data-count>
                    1.000
                  </p>
                  <div className="bar mt-2">
                    <span className="bar-fill" />
                  </div>
                  <p className="mt-2 font-mono text-caption text-muted">
                    vs Chromium innerText · was 0.749
                  </p>
                </div>
              </div>
            </div>
          </article>

          <article className="how-card" data-reveal style={idx(1)}>
            <h3 className="text-h3 font-bold text-ink">Refusals, named</h3>
            <p className="mt-2 text-small text-muted">
              A page it cannot read is a refusal in the engine&rsquo;s own words, not a guess.
              The message names the wall.
            </p>
            <div className="mock mock-refusals" aria-hidden>
              <div className="mock-ui">
                <div className="mock-head">
                  <span className="dot dot-bad" />
                  <span>refusals · resolve.py</span>
                </div>
                <div className="mock-body">
                  {REFUSALS.map(([label, msg], k) => (
                    <div key={label} className="row" style={idx(k)}>
                      <span className="chip chip-bad">{label}</span>
                      <span className="font-mono text-caption text-ink">{msg}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </article>

          <article className="how-card" data-reveal style={idx(2)}>
            <h3 className="text-h3 font-bold text-ink">Provenance</h3>
            <p className="mt-2 text-small text-muted">
              Every quote carries its address: the page, and the block on it. Check it without
              fetching again.
            </p>
            <div className="mock mock-prov" aria-hidden>
              <div className="mock-ui">
                <div className="mock-head">
                  <span className="dot" />
                  <span>citations · url#xpath</span>
                </div>
                <div className="mock-body">
                  {PROVENANCE.map(([anchor, quote], k) => (
                    <div key={anchor} className="row" style={idx(k)}>
                      <span className="anchor font-mono text-caption text-accent-ink">{anchor}</span>
                      <span className="text-caption text-ink">&ldquo;{quote}&rdquo;</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </article>
        </div>

        <p className="mt-6 max-w-prose text-small text-muted" data-reveal>
          Each example is a page this engine met while being measured; the recall is the suite
          in <code className="font-mono">benchmark/fidelity</code>, not yet a per-page score in
          the UI. The{" "}
          <Link href="/report" className="font-medium text-accent-ink underline underline-offset-2">
            Site Truth Report
          </Link>{" "}
          — what a site shows people against what it shows crawlers — runs on any site.
        </p>
      </div>
    </section>
  );
}
