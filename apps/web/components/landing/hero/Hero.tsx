import FieldMount from "./FieldMount";
import HeroStill from "./HeroStill";
import SitePrompt from "./SitePrompt";

/**
 * The hero: the Earth from orbit at sunrise, the universe behind it. Space in both themes --
 * the frame is always dark; the page below keeps its theme. Stars with a magnitude
 * distribution and a faint Milky Way; the planet in the lower third, its limb curving
 * across the frame, the sun rising just above it with long soft rays; the night side's
 * city lights, the day side's oceans, land, clouds and a glint on the water; the air's blue
 * rim. NASA's public-domain Blue Marble, Black Marble and cloud map, credited at the edge.
 *
 * The prompt -- the product's one control -- floats below the headline, above the limb.
 * Websites are worldwide: type an address or hover an example and the planet turns to the
 * site's country (from its country-code domain alone, `lib/country.ts`; nothing is looked
 * up) and a marker glows there; press Run and the camera pushes in before the app opens the
 * run. Server-rendered and complete without JavaScript: the still is the resting frame,
 * rendered once by the same code; `FieldMount` draws the live Earth over it. One frame, one
 * viewport tall, no scroll pinning: the story follows below as its own section. The copy is
 * the promise, verbatim from the story's first chapter. The section is `#start`, where the
 * nav's "Run a site" lands.
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
          <h1 id="hero-title" className="hero-title font-display">
            The honest web reader.
          </h1>
          <p className="hero-lede mx-auto">
            Point it at a website, anywhere in the world. Every public page comes back as
            Markdown in the order a reader sees it, with a note of how each page was obtained —
            and a refusal, named, for every page it could not read.
          </p>
        </div>

        <div className="hero-prompt-slot">
          <SitePrompt scene />
        </div>

        <p className="hero-credit">Earth imagery: NASA</p>
      </div>
    </section>
  );
}
