import Link from "next/link";

/**
 * Brand mark: the limb over the reading lines -- the web seen whole, the page read in order,
 * nothing hidden. The same glyph as `public/logo/mark.svg` and the favicon, drawn inline so it
 * takes the accent tile and the inverse ink of whichever theme is on (design/logo/DECISION in
 * the theme PR). Geometric, 2.4-unit strokes on a 24-unit grid, so it holds at 16px.
 */
export function Mark() {
  return (
    <span aria-hidden className="grid size-7 shrink-0 place-items-center rounded-[6px] bg-accent text-inverse">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
        <path d="M5 10.5 Q12 3.8 19 10.5" />
        <path d="M6.5 14.8 H17.5" />
        <path d="M6.5 19.2 H13.5" />
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
