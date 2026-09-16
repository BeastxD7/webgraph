import type { Route } from "next";

export const REPO = "https://github.com/BeastxD7/webgraph";
export const REPO_ISSUES = `${REPO}/issues/new`;
export const REPO_LICENCE = `${REPO}/blob/main/LICENSE`;

export type NavItem =
  | { label: string; href: Route; external?: false }
  | { label: string; href: string; external: true };

/**
 * `/docs` is being built alongside this branch and has no route file here yet, so typed
 * routes cannot see it. The cast is the whole accommodation; remove it once the route lands.
 */
export const DOCS: Route = "/docs" as Route;

export const NAV: readonly NavItem[] = [
  { label: "Home", href: "/" },
  { label: "Products", href: "/products" },
  { label: "Report", href: "/report" },
  { label: "Watch", href: "/watch" },
  { label: "Docs", href: DOCS },
  { label: "Benchmarks", href: "/benchmarks" },
  { label: "How it works", href: "/how-it-works" },
  { label: "GitHub", href: REPO, external: true },
];

export const FOOTER_LINKS: readonly NavItem[] = [
  { label: "Report", href: "/report" },
  { label: "Docs", href: DOCS },
  { label: "WebGraph", href: "/graph" },
  { label: "Benchmarks", href: "/benchmarks" },
  { label: "How it works", href: "/how-it-works" },
  { label: "Settings", href: "/settings" },
  { label: "GitHub", href: REPO, external: true },
  { label: "Licence — MIT", href: REPO_LICENCE, external: true },
];

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
