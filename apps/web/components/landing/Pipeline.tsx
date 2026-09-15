import { FIDELITY, RENDER_PREDICTION } from "@/lib/benchmarks";

/**
 * How a page is read: three steps on rules, numbered in mono. Replaces the earlier
 * three-stage list, whose counts (132 rules, 18 categories) no longer described the engine;
 * every figure here comes from `lib/benchmarks.ts`.
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

export default function Pipeline() {
  return (
    <section aria-labelledby="reads" className="page-col border-t border-rule py-16 md:py-24">
      <h2 id="reads" className="font-display text-h2 text-ink">
        Two fetches, one page, the reader&rsquo;s order
      </h2>

      <ol className="mt-8 border-t border-rule">
        {STEPS.map((step, index) => (
          <li
            key={step.title}
            className="grid gap-x-8 gap-y-2 border-b border-rule py-6 sm:grid-cols-[3rem_14rem_1fr] md:py-8"
          >
            <span className="font-mono text-label font-medium text-accent-ink" aria-hidden>
              {String(index + 1).padStart(2, "0")}
            </span>
            <h3 className="text-h3 font-bold text-ink">
              <span className="sr-only">Step {index + 1}: </span>
              {step.title}
            </h3>
            <p className="measure-prose text-body text-muted">{step.body}</p>
          </li>
        ))}
      </ol>

      <p className="mt-8 max-w-prose text-caption text-muted">
        Whole-page fidelity, measured against Chromium&rsquo;s innerText on {FIDELITY.sites}{" "}
        sites: word recall 1.000 on {FIDELITY.perfect}, nothing below {FIDELITY.floor}. This is
        a suite in <code className="font-mono">benchmark/fidelity</code>, not yet a per-page
        score in the UI.
      </p>
    </section>
  );
}
