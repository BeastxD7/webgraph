import Link from "next/link";
import type { Route } from "next";

const REPO = "https://github.com/BeastxD7/webgraph";

const LINKS: ReadonlyArray<{ label: string; href: Route }> = [
  { label: "How it works", href: "/#pipeline" },
  { label: "Capabilities", href: "/#capabilities" },
  { label: "Evidence", href: "/#evidence" },
];

/** Brand mark: a page reduced to the three blocks the engine keeps. */
function Mark() {
  return (
    <span
      aria-hidden
      className="grid size-8 shrink-0 place-items-center rounded-[10px] bg-leaf-600 shadow-sm"
    >
      <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
        <rect x="4" y="4" width="12" height="2.4" rx="1.2" fill="white" />
        <rect x="4" y="9" width="8" height="2.4" rx="1.2" fill="white" opacity="0.85" />
        <rect x="4" y="14" width="10" height="2.4" rx="1.2" fill="white" opacity="0.6" />
      </svg>
    </span>
  );
}

export default function SiteHeader() {
  return (
    <header className="relative z-20 mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-5 py-5 sm:px-8">
      <Link
        href="/"
        className="flex items-center gap-2.5 text-[15px] font-extrabold tracking-tight"
      >
        <Mark />
        webgraph
      </Link>

      <nav className="hidden items-center gap-7 text-[13.5px] font-medium text-ink-soft md:flex">
        {LINKS.map((link) => (
          <Link key={link.href} href={link.href} className="transition-colors hover:text-ink">
            {link.label}
          </Link>
        ))}
      </nav>

      <div className="flex items-center gap-2">
        <a
          href={REPO}
          target="_blank"
          rel="noreferrer"
          className="hidden rounded-full border border-line-strong bg-surface/70 px-4 py-2 text-[13px] font-semibold backdrop-blur-sm transition-colors hover:bg-surface sm:block"
        >
          GitHub
        </a>
        <Link
          href="/#start"
          className="rounded-full bg-leaf-600 px-4 py-2 text-[13px] font-semibold text-inverse shadow-sm transition-colors hover:bg-leaf-700"
        >
          Extract a site
        </Link>
      </div>
    </header>
  );
}
