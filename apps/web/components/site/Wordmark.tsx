import Link from "next/link";

/** Brand mark: a page reduced to the three blocks the engine keeps. */
export function Mark() {
  return (
    <span aria-hidden className="grid size-7 shrink-0 place-items-center rounded-sm bg-accent">
      <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
        <rect x="4" y="4" width="12" height="2.4" rx="1.2" fill="var(--inverse)" />
        <rect x="4" y="9" width="8" height="2.4" rx="1.2" fill="var(--inverse)" opacity="0.85" />
        <rect x="4" y="14" width="10" height="2.4" rx="1.2" fill="var(--inverse)" opacity="0.6" />
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
