import Link from "next/link";

import Chip from "@/components/ui/Chip";

/**
 * The product, placed in the scene: one page's run panel as the reader shows it. A real
 * link to the reader, not a picture of one; the field's foreground pages overlap its foot
 * and its shadow falls on the plinth, so it reads as an object standing in the meadow.
 *
 * The figures are one run's: a page whose plain fetch carried 41 words and whose render
 * carried 1,312 (the page needed a browser), the union kept; a route that answered with a
 * login redirect, refused in the engine's own words. `recall 1.000` is the fidelity suite's
 * result on 22 of 29 sites (`FIDELITY`, ProofStrip) -- the same figure the story quotes.
 */
const ROWS: ReadonlyArray<readonly [string, string]> = [
  ["Fetched twice", "static 41 words · rendered 1,312 · union"],
  ["Reading order", "measured · 8 blocks · XY-cut"],
];

export default function RunCard({ className = "" }: { className?: string }) {
  return (
    <Link
      href="/extract"
      data-hero-card
      aria-label="One page read by webgraph: fetched twice, ordered by layout, recall 1.000, a login wall refused. Open the reader."
      className={`hero-card group block rounded-xl border border-rule bg-surface text-left outline-offset-4 ${className}`}
    >
      <div className="flex items-center gap-2.5 border-b border-rule px-4 py-2.5">
        <span aria-hidden className="size-2 shrink-0 rounded-full bg-accent shadow-[0_0_0_3px_var(--accent-soft)]" />
        <span className="min-w-0 flex-1 truncate font-mono text-caption text-muted">
          example.org/docs/reading-a-page
        </span>
        <span className="font-mono text-label font-medium text-faint tabular">1.4s</span>
      </div>
      <dl className="px-4 py-1">
        {ROWS.map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-4 border-b border-rule py-2 last:border-0">
            <dt className="shrink-0 text-caption font-semibold text-muted">{label}</dt>
            <dd className="truncate text-right font-mono text-caption text-ink">{value}</dd>
          </div>
        ))}
        <div className="flex items-center justify-between gap-4 border-b border-rule py-2">
          <dt className="shrink-0 text-caption font-semibold text-muted">Fidelity</dt>
          <dd className="flex items-center gap-2">
            <span className="font-mono text-caption text-ink tabular">recall 1.000</span>
            <Chip tone="measured">measured</Chip>
          </dd>
        </div>
        <div className="flex items-center justify-between gap-4 py-2 max-sm:hidden">
          <dt className="shrink-0 font-mono text-caption text-muted">/account</dt>
          <dd className="min-w-0">
            <Chip tone="refused" className="max-w-full">
              <span className="truncate">refused · redirected to a login page</span>
            </Chip>
          </dd>
        </div>
      </dl>
      <div className="flex items-center justify-between gap-4 border-t border-rule px-4 py-2.5">
        <span className="text-caption text-muted max-sm:hidden">
          Runs on your machine. The only requests made are to the site you name.
        </span>
        <span className="shrink-0 text-caption font-semibold text-accent-ink group-hover:underline">
          Open the reader →
        </span>
      </div>
    </Link>
  );
}
