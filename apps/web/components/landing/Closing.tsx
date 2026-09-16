import type { CSSProperties } from "react";

import SitePrompt from "./hero/SitePrompt";

/**
 * The fifth chapter: run it. The same prompt as the hero's, plain -- no scene to drive -- so
 * a reader who has read the whole story does not have to scroll back up. `#start` is the
 * hero's; the nav's "Run a site" lands there.
 */
export default function Closing() {
  return (
    <section aria-labelledby="run" className="page-col border-t border-rule max-md:py-16 md:py-24">
      <div className="mx-auto max-w-3xl">
        <p className="story-label text-label font-bold uppercase text-muted" data-reveal>
          <span className="font-mono">05</span> · Run it
        </p>
        <h2 id="run" className="mt-4 font-display text-h2 text-ink" data-reveal style={{ "--i": 1 } as CSSProperties}>
          Point it at a site.
        </h2>
        <div className="mt-8" data-reveal style={{ "--i": 2 } as CSSProperties}>
          <SitePrompt />
        </div>
        <p className="mt-3 text-caption text-muted" data-reveal style={{ "--i": 3 } as CSSProperties}>
          Runs on your machine. The only requests made are to the site you name.
        </p>
      </div>
    </section>
  );
}
