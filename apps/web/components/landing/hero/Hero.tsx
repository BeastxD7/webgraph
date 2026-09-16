import FieldMount from "./FieldMount";
import HeroStill from "./HeroStill";
import SitePrompt from "./SitePrompt";

/**
 * The hero: a field of pages at golden hour. Thousands of small paper pages stand in a
 * meadow under a low sun -- the web, as a reader meets it -- and on a plinth in the
 * mid-ground stands the prompt, the product's one control, with the nearest pages rising
 * past its foot. Hover an example, or press Run, and the field organises: pages align into
 * reading order, the dark and the red ones (what the site hides; what a naive reader emits)
 * sink into the ground, a handful lift and thread into the graph of the site, and the run
 * card rises above the prompt as what the address becomes.
 *
 * Server-rendered and complete without JavaScript: the still is inline SVG of the first
 * frame; `FieldMount` draws the live field over it once the WebGL chunk has loaded. One
 * frame, one viewport tall, no scroll pinning: the story follows below as its own section.
 * The copy is the promise, verbatim from the story's first chapter. The section is `#start`,
 * where the nav's "Run a site" lands: the page top, the prompt in view.
 */
export default function Hero() {
  return (
    <section id="start" className="landing-hero scroll-mt-0" aria-labelledby="hero-title">
      <div className="hero-frame" data-hero-frame data-hero-state="idle">
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
        </div>

        <div className="hero-prompt-slot">
          <SitePrompt scene />
        </div>
      </div>
    </section>
  );
}
