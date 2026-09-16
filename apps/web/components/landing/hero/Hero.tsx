import Link from "next/link";

import Button from "@/components/ui/Button";
import { DOCS } from "@/components/site/links";

import FieldMount from "./FieldMount";
import HeroStill from "./HeroStill";
import RunCard from "./RunCard";

/**
 * The hero: a field of pages. Thousands of small paper pages stand in a meadow under a
 * bright sky -- the web, as a reader meets it -- and on a plinth in the mid-ground the
 * product's own run panel stands *in* the scene, with the nearest pages overlapping its
 * foot. As the frame scrolls out the field organises: pages align into reading order, the
 * dark and the red ones (what the site hides; what a naive reader emits) sink into the
 * ground, and a handful lift and thread together into the graph of the site.
 *
 * Server-rendered and complete without JavaScript: the still is inline SVG of the first
 * frame; `FieldMount` draws the live field over it once the WebGL chunk has loaded. The
 * frame is sticky for 70svh of scroll while the field organises; under reduced motion it
 * is not sticky and the field is one still frame. The copy is the promise, verbatim from
 * the story's first chapter; the CTA lands on the prompt (`#start`, Closing).
 */
export default function Hero() {
  return (
    <section className="landing-hero" aria-labelledby="hero-title">
      <div className="hero-track">
        <div className="hero-frame" data-hero-frame>
          <HeroStill />
          <FieldMount />

          <div className="hero-copy">
            <p className="hero-badge">
              <span aria-hidden className="size-1.5 rounded-full bg-accent" />
              Open source · Runs locally · MIT
            </p>
            <h1 id="hero-title" className="hero-title font-display text-ink">
              The honest web reader.
            </h1>
            <p className="hero-lede mx-auto text-ink">
              Point it at a website. Every public page comes back as Markdown in the order a
              reader sees it, with a note of how each page was obtained — and a refusal, named,
              for every page it could not read.
            </p>
            <div className="mt-7 flex flex-wrap items-center justify-center gap-x-5 gap-y-3">
              <Button href="/#start" className="h-11 px-5 text-body">
                Run a site
              </Button>
              <Link
                href={DOCS}
                className="text-small font-semibold text-ink underline decoration-rule-strong underline-offset-4 hover:decoration-ink"
              >
                Read the docs →
              </Link>
            </div>
          </div>

          <div className="hero-card-slot">
            <RunCard />
          </div>
        </div>
      </div>
    </section>
  );
}
