import type { CSSProperties } from "react";

import Link from "next/link";

import Button from "@/components/ui/Button";
import { DOCS } from "@/components/site/links";
import { FIDELITY, RENDER_PREDICTION } from "@/lib/benchmarks";

import type { StageCopy } from "./scene/scene";
import Stage from "./Stage";
import StoryStill from "./StoryStill";

/**
 * The landing's first four chapters on one sticky stage: the promise (hero), the pain, the
 * turn and the result. The copy is server-rendered and scrolls past the stage; `Stage`
 * reads how far it has scrolled and morphs the scene. The proof (ProofStrip, RefusesDrops,
 * Standings) and the run prompt (Closing) follow as ordinary sections.
 *
 * Every figure here is read from `lib/benchmarks.ts`; every example is one the changelog
 * records. The three steps are the former Pipeline section, verbatim, folded into chapter 2.
 */
const STEPS: ReadonlyArray<{ title: string; body: string }> = [
  {
    title: "Fetch twice",
    body:
      "A plain request and a real Chromium render, 1440×900. Neither alone is complete: " +
      "rendering loses server markup on hydration; static misses what scripts insert. " +
      `Predicting which a page needs scored ${RENDER_PREDICTION.hit} of ${RENDER_PREDICTION.of}, ` +
      "so the engine stopped predicting.",
  },
  {
    title: "Merge",
    body:
      "Blocks are matched by content and unioned. What the browser hid is not put back. A " +
      "wall on one side is left out and named.",
  },
  {
    title: "Order by layout",
    body:
      "Every element is measured. Reading order is a recursive XY-cut over the boxes — " +
      "columns stay columns. Where no geometry exists the order is source order and the " +
      "page says “assumed”, not “measured”.",
  },
];

export const STAGE_COPY: StageCopy = {
  fidelity: `recall 1.000 on ${FIDELITY.perfect} of ${FIDELITY.sites} sites · floor ${FIDELITY.floor}`,
  report: [
    ["hidden text", "2,100 words · 9 closed dialogs"],
    ["off-screen links", "~60 · left: −9999px"],
    ["hidden contents list", "100 links · display:none"],
  ],
};

/** Stagger index for the reveal transition (`--i` × 70ms). */
const idx = (i: number) => ({ "--i": i }) as CSSProperties;

const PANEL =
  "story-panel flex flex-col justify-center max-lg:min-h-[58svh] max-lg:py-12 lg:min-h-[calc(100dvh-3.5rem)] lg:py-16";

export default function Story() {
  return (
    <section
      data-story
      aria-labelledby="hero-title"
      className="page-col relative lg:grid lg:grid-cols-12 lg:gap-x-8"
    >
      {/* The stage: sticky under the header. On a phone it is a band at the top the copy
          slides beneath; from lg it is the right seven columns. */}
      <div className="max-lg:sticky max-lg:top-14 max-lg:z-10 max-lg:-mx-(--gutter) max-lg:bg-ground max-lg:px-(--gutter) lg:order-2 lg:col-span-7">
        <div className="story-stage relative max-lg:h-[38svh] max-lg:overflow-hidden lg:sticky lg:top-14 lg:h-[calc(100dvh-3.5rem)]">
          <div className="absolute inset-0 max-lg:py-2 lg:py-8">
            <div className="relative size-full">
              <StoryStill copy={STAGE_COPY} />
              <Stage copy={STAGE_COPY} />
              {/* The report card on the canvas is a link: Stage places this over it. */}
              <Link
                href="/report"
                data-report-link
                hidden
                aria-label="Site Truth Report — run it on any site"
                className="absolute rounded-md outline-offset-2"
              />
            </div>
          </div>
        </div>
      </div>

      <div className="lg:order-1 lg:col-span-5">
        {/* 0 — the promise */}
        <div className={`${PANEL} max-lg:pt-8`} data-panel="0">
          <p className="text-label font-bold uppercase text-muted">Open-source · Runs locally · MIT</p>
          <h1 id="hero-title" className="mt-5 font-display text-display text-ink">
            The honest web reader.
          </h1>
          <p className="measure-lede mt-6 text-body text-muted">
            Point it at a website. Every public page comes back as Markdown in the order a
            reader sees it, with a note of how each page was obtained — and a refusal, named,
            for every page it could not read.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Button href="/#start">Run a site</Button>
            <Button href={DOCS} variant="secondary">
              Read the docs
            </Button>
          </div>
          <p className="mt-4 text-caption text-muted">
            Runs on your machine. The only requests made are to the site you name.
          </p>
        </div>

        {/* 1 — the pain */}
        <div className={PANEL} data-panel="1">
          <p className="story-label text-label font-bold uppercase text-muted">
            <span className="font-mono">01</span> · The problem
          </p>
          <h2 className="mt-4 font-display text-h2 text-ink" data-reveal>
            You pointed your AI at a website. It read the wrong things.
          </h2>
          <p className="measure-lede mt-4 text-body text-muted" data-reveal style={idx(1)}>
            A cookie banner returned as the article. A login page passed off as the page. A
            503, extracted as text. Words missing because the page needed a browser. Sixty
            gambling links no reader ever saw, faithfully included.
          </p>
          <p className="mt-5 max-w-prose text-caption text-muted" data-reveal style={idx(2)}>
            Each is a page this engine met while being measured: a consent dialog chosen as
            the thread, ~60 off-screen links on every page of one university site, 2,100 words
            in nine <code className="font-mono">display:none</code> dialogs on one government
            site. Oxide red marks what a naive reader emits as content; ochre, what it cannot
            know it is missing.
          </p>
        </div>

        {/* 2 — the turn */}
        <div className={PANEL} data-panel="2">
          <p className="story-label text-label font-bold uppercase text-muted">
            <span className="font-mono">02</span> · The turn
          </p>
          <h2 className="mt-4 font-display text-h2 text-ink" data-reveal>
            Two fetches, one page, the reader&rsquo;s order
          </h2>
          <p className="measure-lede mt-4 text-body text-muted" data-reveal style={idx(1)}>
            Read it the way a person does. A wall is not a page: it is refused, in the
            engine&rsquo;s own words, and what the browser hides stays hidden.
          </p>
          <ol className="mt-6 border-t border-rule">
            {STEPS.map((step, index) => (
              <li
                key={step.title}
                className="grid gap-x-4 gap-y-1 border-b border-rule py-4 sm:grid-cols-[2.25rem_1fr]"
                data-reveal
                style={idx(index + 2)}
              >
                <span className="font-mono text-label font-medium text-accent-ink" aria-hidden>
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div>
                  <h3 className="text-h3 font-bold text-ink">
                    <span className="sr-only">Step {index + 1}: </span>
                    {step.title}
                  </h3>
                  <p className="mt-1 text-small text-muted">{step.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>

        {/* 3 — the result */}
        <div className={PANEL} data-panel="3">
          <p className="story-label text-label font-bold uppercase text-muted">
            <span className="font-mono">03</span> · The result
          </p>
          <h2 className="mt-4 font-display text-h2 text-ink" data-reveal>
            Markdown in reading order, with a note of how it knows.
          </h2>
          <p className="measure-lede mt-4 text-body text-muted" data-reveal style={idx(1)}>
            Every page says whether its order was measured or assumed, how it was fetched, and
            what was refused. Each page links to the pages it reaches, so the crawl is a map of
            the site. The{" "}
            <Link href="/report" className="font-medium text-accent-ink underline underline-offset-2">
              Site Truth Report
            </Link>{" "}
            — what a site shows people against what it shows crawlers — run it on any site.
          </p>
          <p className="mt-5 max-w-prose text-caption text-muted" data-reveal style={idx(2)}>
            Whole-page fidelity, measured against Chromium&rsquo;s innerText on {FIDELITY.sites}{" "}
            sites: word recall 1.000 on {FIDELITY.perfect}, nothing below {FIDELITY.floor}. This is
            a suite in <code className="font-mono">benchmark/fidelity</code>, not yet a per-page
            score in the UI.
          </p>
        </div>
      </div>
    </section>
  );
}
