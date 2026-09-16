import EvidenceRow from "@/components/ui/EvidenceRow";

/**
 * Two columns: what the engine refuses, in its own words, and what it leaves out because a
 * reader would not have seen it. Both lists are the engine's behaviour as shipped; every
 * message is quoted from `resolve.py` and every example from the changelog.
 */
const REFUSES: ReadonlyArray<{ label: string; value: string; source?: string; mono?: boolean }> = [
  {
    label: "HTTP 5xx",
    value: "A render answered with a server error is a failed side, not content.",
    source: "The plain fetch stands alone and the render's status is reported beside it.",
  },
  {
    label: "Login redirect",
    value: "redirected to a login page (…); the page requires a sign-in and nothing of it was served",
    mono: true,
  },
  {
    label: "Bot challenge",
    value: "Vendor named: Cloudflare, AWS WAF, DataDome, PerimeterX, Akamai, Kasada, Imperva.",
    source: "the site answered with a Cloudflare bot challenge — a script a browser must run before the page is served — and no page",
  },
  {
    label: "Block page",
    value: 'it said: "You\'ve been blocked…"',
    source: "The block page's own words, quoted; never passed off as the page.",
    mono: true,
  },
  {
    label: "404 / 410",
    value: "HTTP 404: page does not exist",
    source: "Never rendered — a browser renders a 404 page too.",
    mono: true,
  },
  {
    label: "robots.txt",
    value: "The site asked; the message says what it offers instead.",
    source: "The rules that applied to this client are shown with the run.",
  },
];

const DROPS: ReadonlyArray<{ label: string; value: string; source?: string }> = [
  {
    label: "display:none, visibility:hidden",
    value: "Dropped.",
    source: "php.net's hidden 100-link table of contents.",
  },
  {
    label: "Off-screen, negative coordinates",
    value: "Dropped.",
    source: "Injected links a reader never sees: ~60 gambling links on every page of vtu.ac.in.",
  },
  {
    label: "Closed modals",
    value: "Dropped.",
    source: "2,100 words in nine display:none dialogs on one government site.",
  },
  {
    label: "Consent dialogs, share bars, “most read” rails",
    value: "Left out of content.",
  },
  {
    label: "Alt text, screen-reader-only text",
    value: "Not page text.",
    source: "Kept on request; a sighted reader never saw it.",
  },
  {
    label: "A wall served to one fetch",
    value: "Left out, and named.",
    source: "The other fetch stands alone; the union does not put the wall's words back.",
  },
];

export default function RefusesDrops() {
  return (
    <section aria-labelledby="refuses" className="page-col border-t border-rule max-md:py-16 md:py-24">
      <div className="grid gap-12 lg:grid-cols-2 lg:gap-16">
        <div className="min-w-0">
          <h2 id="refuses" className="font-display text-h2 text-ink" data-reveal>
            Refuses, and says why
          </h2>
          <p className="measure-lede mt-3 text-body text-muted">
            A page it cannot read is a refusal, not a guess. The message names the wall.
          </p>
          <dl className="mt-6 border-t border-rule">
            {REFUSES.map((row, i) => (
              <EvidenceRow key={row.label} {...row} index={i} />
            ))}
          </dl>
        </div>

        <div className="min-w-0">
          <h2 className="font-display text-h2 text-ink" data-reveal>
            Drops what the site hides
          </h2>
          <p className="measure-lede mt-3 text-body text-muted">
            What a browser hides from a reader stays hidden in the output, even when the HTML
            holds it.
          </p>
          <dl className="mt-6 border-t border-rule">
            {DROPS.map((row, i) => (
              <EvidenceRow key={row.label} {...row} index={i} />
            ))}
          </dl>
        </div>
      </div>

      <p className="mt-8 max-w-prose text-caption text-muted" data-reveal>
        Refusal kinds are login · challenge · block · undeclared, from the engine&rsquo;s own
        error types. An open cookie prompt is on the page and is judged like anything else.
      </p>
    </section>
  );
}
