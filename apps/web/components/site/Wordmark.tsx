import Link from "next/link";
import { useId } from "react";

/**
 * Brand mark: the constellation w -- a knowledge graph that spells the initial, drawn as four
 * ribbons that tuck under four matte nodes, its top-right corner open and its brightest star, a
 * four-point sparkle, aglow in the gap. The site becomes a graph, and the graph travels, to
 * people and to the agents that will read it. The hue is the hero's own atmosphere, on the
 * `--brand-*` tokens (globals.css §1/§1b) so it follows the theme; the same drawing as
 * `public/logo/mark.svg` / `mark-dark.svg`. Under ~24 px the flat form is used instead
 * (`mark-flat.svg`, `mark-mono.svg`, the favicon).
 *
 * The gradient and filter ids are unique per instance (`useId`). An SVG paint server is
 * looked up by id across the whole document, and the docs layout renders the mark twice --
 * once in the desktop sidebar, once in the collapsed mobile header, one of them
 * `display: none`. With fixed ids every instance resolved its gradient to the *first*
 * one in the document, which sat in the hidden copy and therefore painted nothing: the
 * ribbons vanished and the nodes went grey in the docs while the landing page, with one
 * mark, was fine.
 */
export function Mark() {
  const id = useId();
  const g = `${id}g`;
  const n = `${id}n`;
  const b = `${id}b`;
  const w = `${id}w`;
  return (
    <svg aria-hidden className="mark size-7 shrink-0" viewBox="0 0 24 24">
      <defs>
        <linearGradient id={g} gradientUnits="userSpaceOnUse" x1="2" y1="22" x2="22" y2="2">
          <stop offset="0" style={{ stopColor: "var(--brand-a)" }} />
          <stop offset="1" style={{ stopColor: "var(--brand-b)" }} />
        </linearGradient>
        <radialGradient id={n} cx="0.62" cy="0.32" r="0.9">
          <stop offset="0" style={{ stopColor: "var(--brand-hi)" }} />
          <stop offset="1" style={{ stopColor: "var(--brand-b)" }} />
        </radialGradient>
        <filter id={b} x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="0.7" /></filter>
        <filter id={w} x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="0.7" /></filter>
      </defs>
      <g>
        <path d="M3.00 8.50 L7.50 20.00" fill="none" stroke={`url(#${g})`} strokeWidth="2.7" strokeLinecap="round" />
        <path d="M7.50 20.00 L11.50 12.00" fill="none" stroke={`url(#${g})`} strokeWidth="2.7" strokeLinecap="round" />
        <path d="M11.50 12.00 L15.50 20.00" fill="none" stroke={`url(#${g})`} strokeWidth="2.7" strokeLinecap="round" />
        <path d="M15.50 20.00 L18.11 13.33" fill="none" stroke={`url(#${g})`} strokeWidth="2.7" strokeLinecap="round" />
        <circle cx="3" cy="8.5" r="3.50" style={{ fill: "var(--brand-shade)" }} opacity="0.38" filter={`url(#${b})`} />
        <circle cx="7.5" cy="20.0" r="3.10" style={{ fill: "var(--brand-shade)" }} opacity="0.38" filter={`url(#${b})`} />
        <circle cx="11.5" cy="12.0" r="2.80" style={{ fill: "var(--brand-shade)" }} opacity="0.38" filter={`url(#${b})`} />
        <circle cx="15.5" cy="20.0" r="3.10" style={{ fill: "var(--brand-shade)" }} opacity="0.38" filter={`url(#${b})`} />
        <circle cx="3" cy="8.5" r="3.10" fill={`url(#${n})`} />
        <circle cx="7.5" cy="20.0" r="2.70" fill={`url(#${n})`} />
        <circle cx="11.5" cy="12.0" r="2.40" fill={`url(#${n})`} />
        <circle cx="15.5" cy="20.0" r="2.70" fill={`url(#${n})`} />
        <path d="M17.40 0.48 Q17.40 6.30 23.22 6.30 Q17.40 6.30 17.40 12.12 Q17.40 6.30 11.58 6.30 Q17.40 6.30 17.40 0.48 Z" style={{ fill: "var(--brand-glow)" }} opacity="0.5" filter={`url(#${w})`} />
        <path d="M17.40 1.10 Q17.40 6.30 22.60 6.30 Q17.40 6.30 17.40 11.50 Q17.40 6.30 12.20 6.30 Q17.40 6.30 17.40 1.10 Z" style={{ fill: "var(--brand-star)" }} />
        <path d="M17.40 4.12 Q17.40 6.30 19.58 6.30 Q17.40 6.30 17.40 8.48 Q17.40 6.30 15.22 6.30 Q17.40 6.30 17.40 4.12 Z" style={{ fill: "var(--brand-core)" }} opacity="0.9" />
      </g>
    </svg>
  );
}

export default function Wordmark({ className = "" }: { className?: string }) {
  return (
    <Link
      href="/"
      className={`wordmark-text inline-flex items-center gap-2.5 text-[15px] font-bold tracking-tight text-ink ${className}`}
    >
      <Mark />
      WebGraph
    </Link>
  );
}
