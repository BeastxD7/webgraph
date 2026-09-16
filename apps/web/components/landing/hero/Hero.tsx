import FieldMount from "./FieldMount";
import HeroStill from "./HeroStill";
import SitePrompt from "./SitePrompt";

/**
 * The hero: the Earth from orbit, in the page's theme. By night (the dark theme) the
 * sunrise: stars with a magnitude distribution and a faint Milky Way, the planet in the
 * lower third with its limb curving across the frame, the sun rising from behind it with
 * long soft rays, the night side's city lights. By day (the light theme) the same orbit in
 * full sun: bright ocean, cloud decks with their shadows, the thick pale-blue air at the
 * limb fading into a light sky. Either way the day side's oceans, land, clouds and a glint
 * on the water, and the air's rim. NASA's public-domain Blue Marble, Black Marble and cloud
 * map, credited at the edge. Switching the theme crosses the scene over 600 ms.
 *
 * The prompt -- the product's one control -- floats below the headline, above the limb.
 * Websites are worldwide: type an address or hover an example and the planet turns to the
 * site's country (from its country-code domain alone, `lib/country.ts`; nothing is looked
 * up) and a marker glows there; press Run and the camera pushes in before the app opens the
 * run. Server-rendered and complete without JavaScript: the still is the resting frame in
 * each theme, rendered once by the same code; `FieldMount` draws the live Earth over it.
 * One frame, one viewport tall, no scroll pinning: the story follows below as its own
 * section. The copy sits in the first of three rows over the scene; the run card gets the
 * middle row, and shows only where that row is tall enough for it not to touch the
 * sub-line; the prompt sits at the row's foot, above the limb. The section is `#start`,
 * where the nav's "Run a site" lands.
 */
export default function Hero() {
  return (
    <section id="start" className="landing-hero scroll-mt-0" aria-labelledby="hero-title">
      <div className="hero-frame" data-hero-frame data-hero-state="idle">
        <HeroStill />
        <FieldMount />

        <div className="hero-layout">
          <div className="hero-copy">
            <p className="hero-badge">
              <span aria-hidden className="size-1.5 rounded-full bg-accent" />
              Open source · Runs locally · MIT
            </p>
            <h1 id="hero-title" className="hero-title font-display">
              The honest web reader.
            </h1>
            <p className="hero-lede">
              Point it at a website, anywhere in the world. Every public page comes back as
              Markdown in the order a reader sees it, with a note of how each page was obtained —
              and a refusal, named, for every page it could not read.
            </p>
          </div>

          <div className="hero-room">
            <div className="hero-prompt-slot">
              <SitePrompt scene />
            </div>
          </div>
        </div>

        <p className="hero-credit">Earth imagery: NASA</p>
      </div>
    </section>
  );
}
