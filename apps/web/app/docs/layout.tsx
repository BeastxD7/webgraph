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
      // `attribute`/`storageKey` match `lib/theme.ts` exactly (same `data-theme` attribute,
      // same localStorage key) so this provider and the rest of the site's own toggle read
      // and write one shared preference instead of two that can disagree. Left at
      // next-themes' default (`class`), a change made from the docs sidebar's own
      // light/dark control updated fumadocs' styling but never touched `data-theme` --
      // reported live as "themeing is not working in docs sidebar", reproduced by toggling
      // it and finding `data-theme` stuck on its old value while `class` and localStorage
      // had both moved on.
      //
      // The dark palette in docs.css is still gated on the docs layout being present
      // (`[data-theme="dark"]:has(#nd-docs-layout)`), because the stylesheet that carries
      // it is never unloaded on a client-side navigation away from /docs -- not to stop a
      // leftover attribute from restyling the rest of the site (the rest of the site is
      // *supposed* to follow `data-theme`; that is the point of sharing it), but to keep
      // docs-only `--color-fd-*` variable overrides from staying live outside the subtree
      // that reads them. `enableColorScheme` would write an inline `color-scheme` to
      // <html> the same way; docs.css sets it inside the same gate instead.
      theme={{ enableColorScheme: false, attribute: "data-theme", storageKey: "theme" }}
    >
      <DocsLayout
        tree={source.getPageTree()}
        nav={{
          title: (
            <span className="flex items-center gap-2.5 text-[15px] font-bold tracking-tight text-ink">
              <Mark />
              WebGraph
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
