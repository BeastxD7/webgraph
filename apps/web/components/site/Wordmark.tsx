import Link from "next/link";

/**
 * Brand mark: the constellation w -- a knowledge graph that spells the initial, drawn as four
 * ribbons that tuck under four spheres, its top-right corner open and its brightest star, a
 * four-point sparkle, aglow in the gap. The site becomes a graph, and the graph travels, to
 * people and to the agents that will read it. The hue is the hero's own atmosphere, on the
 * `--brand-*` tokens (globals.css §1/§1b) so it follows the theme; the same drawing as
 * `public/logo/mark.svg` / `mark-dark.svg`. Under ~24 px the flat form is used instead
 * (`mark-flat.svg`, `mark-mono.svg`, the favicon).
 */
export function Mark() {
  return (
    <svg aria-hidden className="mark size-7 shrink-0" viewBox="0 0 24 24">
      <defs>
        <linearGradient id="mk-g" gradientUnits="userSpaceOnUse" x1="2" y1="22" x2="22" y2="2">
          <stop offset="0" style={{ stopColor: "var(--brand-a)" }} />
          <stop offset="1" style={{ stopColor: "var(--brand-b)" }} />
        </linearGradient>
        <radialGradient id="mk-n" cx="0.38" cy="0.34" r="0.75">
          <stop offset="0" style={{ stopColor: "var(--brand-hi)" }} />
          <stop offset="0.45" style={{ stopColor: "var(--brand-b)" }} />
          <stop offset="1" style={{ stopColor: "var(--brand-a)" }} />
        </radialGradient>
        <filter id="mk-b" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="0.55" /></filter>
        <filter id="mk-w" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="1.1" /></filter>
      </defs>
      <g>
        <path d="M3.00 8.50 L7.50 20.00" fill="none" stroke="url(#mk-g)" strokeWidth="3.1" strokeLinecap="round" />
        <path d="M7.50 20.00 L11.50 12.00" fill="none" stroke="url(#mk-g)" strokeWidth="3.1" strokeLinecap="round" />
        <path d="M11.50 12.00 L15.50 20.00" fill="none" stroke="url(#mk-g)" strokeWidth="3.1" strokeLinecap="round" />
        <path d="M15.50 20.00 L18.11 13.33" fill="none" stroke="url(#mk-g)" strokeWidth="3.1" strokeLinecap="round" />
        <circle cx="3" cy="8.5" r="3.60" style={{ fill: "var(--brand-shade)" }} opacity="0.45" filter="url(#mk-b)" />
        <circle cx="7.5" cy="20.0" r="3.20" style={{ fill: "var(--brand-shade)" }} opacity="0.45" filter="url(#mk-b)" />
        <circle cx="11.5" cy="12.0" r="2.90" style={{ fill: "var(--brand-shade)" }} opacity="0.45" filter="url(#mk-b)" />
        <circle cx="15.5" cy="20.0" r="3.20" style={{ fill: "var(--brand-shade)" }} opacity="0.45" filter="url(#mk-b)" />
        <circle cx="3" cy="8.5" r="3.10" fill="url(#mk-n)" />
        <circle cx="7.5" cy="20.0" r="2.70" fill="url(#mk-n)" />
        <circle cx="11.5" cy="12.0" r="2.40" fill="url(#mk-n)" />
        <circle cx="15.5" cy="20.0" r="2.70" fill="url(#mk-n)" />
        <path d="M17.40 -0.20 Q17.40 6.30 23.90 6.30 Q17.40 6.30 17.40 12.80 Q17.40 6.30 10.90 6.30 Q17.40 6.30 17.40 -0.20 Z" style={{ fill: "var(--brand-glow)" }} opacity="0.55" filter="url(#mk-w)" />
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
      webgraph
    </Link>
  );
}
