import Chip from "@/components/ui/Chip";

import type { Mode } from "./SitePrompt";

/**
 * What an address becomes: one page's run panel as the reader shows it, rising above the
 * prompt while an example is hovered or a run starts. A preview, so decorative to a screen
 * reader; the prompt's mode hint says the same in words.
 *
 * The figures are one run's: a page whose plain fetch carried 41 words and whose render
 * carried 1,312 (the page needed a browser), the union kept; a route that answered with a
 * login redirect, refused in the engine's own words. `recall 1.000` is the fidelity suite's
 * result on 22 of 29 sites (`FIDELITY`, ProofStrip) -- the figure the story quotes. In the
 * report mode the rows are the Site Truth Report's (`STAGE_COPY` in Story.tsx, the changelog).
 */
const ROWS: Record<Mode, ReadonlyArray<readonly [string, string]>> = {
  page: [
    ["Fetched twice", "static 41 words · rendered 1,312 · union"],
    ["Reading order", "measured · 8 blocks · XY-cut"],
  ],
  site: [
    ["Fetched twice", "static 41 words · rendered 1,312 · union"],
    ["Reading order", "measured · 8 blocks · XY-cut"],
  ],
  report: [
    ["Hidden text", "2,100 words · 9 closed dialogs"],
    ["Off-screen links", "~60 · left: −9999px"],
  ],
};

export default function RunCard({ host, mode }: { host: string; mode: Mode }) {
  return (
    <div aria-hidden className="hero-card rounded-xl border border-rule bg-surface text-left">
      <div className="flex items-center gap-2.5 border-b border-rule px-4 py-2.5">
        <span className="size-2 shrink-0 rounded-full bg-accent shadow-[0_0_0_3px_var(--accent-soft)]" />
        <span className="min-w-0 flex-1 truncate font-mono text-caption text-muted">
          {host}
        </span>
        <span className="font-mono text-label font-medium text-muted tabular">1.4s</span>
      </div>
      <dl className="px-4 py-1">
        {ROWS[mode].map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-4 border-b border-rule py-2">
            <dt className="shrink-0 text-caption font-semibold text-muted">{label}</dt>
            <dd className="truncate text-right font-mono text-caption text-ink">{value}</dd>
          </div>
        ))}
        {mode === "report" ? (
          <div className="flex items-center justify-between gap-4 py-2">
            <dt className="shrink-0 text-caption font-semibold text-muted">Hidden contents list</dt>
            <dd className="flex items-center gap-2">
              <span className="font-mono text-caption text-ink">100 links · display:none</span>
              <Chip tone="refused">dropped</Chip>
            </dd>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between gap-4 border-b border-rule py-2">
              <dt className="shrink-0 text-caption font-semibold text-muted">Fidelity</dt>
              <dd className="flex items-center gap-2">
                <span className="font-mono text-caption text-ink tabular">recall 1.000</span>
                <Chip tone="measured">measured</Chip>
              </dd>
            </div>
            <div className="flex items-center justify-between gap-4 py-2">
              <dt className="shrink-0 font-mono text-caption text-muted">/account</dt>
              <dd className="min-w-0">
                <Chip tone="refused" className="max-w-full">
                  <span className="truncate">refused · redirected to a login page</span>
                </Chip>
              </dd>
            </div>
          </>
        )}
      </dl>
    </div>
  );
}
