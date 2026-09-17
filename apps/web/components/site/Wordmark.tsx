import Link from "next/link";

/**
 * Brand mark: the constellation w -- five nodes and four edges, a knowledge graph that spells
 * the initial, its brightest star (a four-point star) at the top right; a constellation, so
 * it belongs with the space of the hero. The site becomes a graph, and the graph travels --
 * to people and to agents. The same glyph as `public/logo/mark.svg`, drawn inline so it takes
 * the accent tile and the inverse ink of whichever theme is on. On a 24-unit grid: the outer
 * nodes are the hubs, the inner ones smaller. The favicon is the 16 px form, where the star
 * is a larger dot (its arms merge at that size).
 */
export function Mark() {
  return (
    <span aria-hidden className="grid size-7 shrink-0 place-items-center rounded-[6px] bg-accent text-inverse">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
        <path d="M4.5 7.5 L8.5 17 L12 10.5 L15.5 17 L18.8 7.9" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="4.5" cy="7.5" r="2.5" />
        <circle cx="8.5" cy="17" r="2.1" />
        <circle cx="15.5" cy="17" r="2.1" />
        <circle cx="12" cy="10.5" r="1.8" />
        <path d="M18.80 4.30 L19.95 6.75 L22.40 7.90 L19.95 9.05 L18.80 11.50 L17.65 9.05 L15.20 7.90 L17.65 6.75 Z" />
      </svg>
    </span>
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
