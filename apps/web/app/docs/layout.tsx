import type { ReactNode } from "react";
import { DocsLayout } from "fumadocs-ui/layouts/docs";
import { RootProvider } from "fumadocs-ui/provider/next";

import { Mark } from "@/components/site/SiteHeader";
import { source } from "@/lib/source";

import "./docs.css";

const REPO = "https://github.com/BeastxD7/webgraph";

/**
 * The documentation shell. Fumadocs' provider (theme, search dialog, sidebar state) lives
 * here rather than in the root layout so the rest of the site is untouched by it; the
 * stylesheet is likewise loaded only under /docs.
 */
export default function DocsRootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <RootProvider
      // The dark palette in docs.css is gated on the docs layout being present, so a
      // `.dark` class left on <html> after navigating away cannot restyle the site.
      // `enableColorScheme` would write an inline `color-scheme` to <html> the same way;
      // docs.css sets it inside the same gate instead.
      theme={{ enableColorScheme: false }}
    >
      <DocsLayout
        tree={source.getPageTree()}
        nav={{
          title: (
            <span className="flex items-center gap-2.5 text-[15px] font-bold tracking-tight text-ink">
              <Mark />
              webgraph
            </span>
          ),
          url: "/",
        }}
        links={[
          { text: "How it works", url: "/how-it-works" },
          { text: "Benchmarks", url: "/benchmarks" },
          { text: "Extract a site", url: "/#start" },
        ]}
        githubUrl={REPO}
      >
        {children}
      </DocsLayout>
    </RootProvider>
  );
}
