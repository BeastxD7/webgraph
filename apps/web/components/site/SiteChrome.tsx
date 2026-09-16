"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

/**
 * The site header and footer, everywhere but under /docs.
 *
 * The documentation shell (app/docs/layout.tsx, Fumadocs) draws its own top bar, sidebar
 * and links, and a second bar above it would be two navigations on one page. Until the
 * docs shell shares this header (DESIGN.md §4c wants one provider for the whole site), it
 * steps aside there.
 */
export default function SiteChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (pathname === "/docs" || pathname.startsWith("/docs/")) return null;
  return <>{children}</>;
}
