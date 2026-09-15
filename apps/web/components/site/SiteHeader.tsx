"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useState, useSyncExternalStore } from "react";

import Button from "@/components/ui/Button";
import ThemeToggle from "@/components/ui/ThemeToggle";

import { isActive, NAV, type NavItem } from "./links";
import Wordmark from "./Wordmark";

/**
 * One bar for every page (DESIGN.md §4d).
 *
 * Sits on the page ground and takes the surface colour with a rule once the page has moved
 * 8px, so the bar reads as part of the page at rest and as a bar once content scrolls under
 * it. Below the `nav` breakpoint the items fold behind a button that says "Menu" -- the word,
 * not a glyph alone -- and open as a full-width sheet under the bar.
 */
export default function SiteHeader() {
  const pathname = usePathname();
  const scrolled = useSyncExternalStore(subscribeScroll, isScrolled, () => false);
  // The sheet is open *for a path*: a navigation changes the path and so closes it, with no
  // effect needed to do the closing.
  const [openAt, setOpenAt] = useState<string | null>(null);
  const open = openAt === pathname;
  const setOpen = (next: boolean) => setOpenAt(next ? pathname : null);
  const sheetId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpenAt(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const bar = scrolled || open ? "bg-surface border-rule" : "bg-ground border-transparent";

  return (
    <header
      className={`sticky top-0 z-30 border-b transition-colors duration-(--dur-base) ease-(--ease) ${bar}`}
    >
      <div className="page-col flex h-14 items-center gap-4">
        <Wordmark />

        <nav aria-label="Site" className="hidden flex-1 items-center gap-6 nav:flex">
          {NAV.map((item) => (
            <NavLink key={item.label} item={item} active={isActive(pathname, item.href)} />
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-1.5">
          <ThemeToggle />
          {/* Wrapped: the button's own `inline-flex` would otherwise fight `hidden`. */}
          <div className="hidden nav:block">
            <Button href="/#start">Run a site</Button>
          </div>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={sheetId}
            onClick={() => setOpen(!open)}
            className="inline-flex h-9 items-center rounded-md px-3 text-small font-semibold text-muted hover:text-ink active:bg-sunk pointer-coarse:min-h-11 nav:hidden"
          >
            {open ? "Close" : "Menu"}
          </button>
        </div>
      </div>

      {/* The sheet. Rendered only while open so it is not in the tab order otherwise. */}
      {open && (
        <div
          id={sheetId}
          className="absolute inset-x-0 top-full border-b border-rule bg-surface nav:hidden"
        >
          <nav aria-label="Site, menu" className="page-col">
            <ul className="divide-y divide-rule">
              {NAV.map((item) => (
                <li key={item.label}>
                  <SheetLink item={item} active={isActive(pathname, item.href)} />
                </li>
              ))}
              <li className="py-3">
                <Button href="/#start" className="w-full">
                  Run a site
                </Button>
              </li>
            </ul>
          </nav>
        </div>
      )}
    </header>
  );
}

function subscribeScroll(listener: () => void): () => void {
  window.addEventListener("scroll", listener, { passive: true });
  return () => window.removeEventListener("scroll", listener);
}

function isScrolled(): boolean {
  return window.scrollY > 8;
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const classes = `text-small font-medium transition-colors duration-(--dur-fast) hover:text-ink ${
    active ? "text-ink" : "text-muted"
  }`;
  if (item.external) {
    return (
      <a href={item.href} target="_blank" rel="noreferrer" className={classes}>
        {item.label} <span aria-hidden>↗</span>
      </a>
    );
  }
  return (
    <Link href={item.href} aria-current={active ? "page" : undefined} className={classes}>
      {item.label}
    </Link>
  );
}

function SheetLink({ item, active }: { item: NavItem; active: boolean }) {
  const classes = `flex min-h-12 items-center text-body ${active ? "font-semibold text-ink" : "text-ink"}`;
  if (item.external) {
    return (
      <a href={item.href} target="_blank" rel="noreferrer" className={classes}>
        {item.label} <span aria-hidden className="ml-1">↗</span>
      </a>
    );
  }
  return (
    <Link href={item.href} aria-current={active ? "page" : undefined} className={classes}>
      {item.label}
    </Link>
  );
}
