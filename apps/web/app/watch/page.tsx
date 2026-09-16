import type { Metadata } from "next";

import WatchPanel from "@/components/watch/WatchPanel";

export const metadata: Metadata = {
  title: "Watch",
  description:
    "Watch a site for changes: every run says which page and which section changed, in the page's own words, and leaves timestamps and counters out.",
};

export default function WatchPage() {
  return (
    <main className="page-col max-md:pb-16 max-md:pt-12 md:pb-24 md:pt-20">
      <header>
        <h1 className="font-display text-h1 text-ink">Watch</h1>
        <p className="measure-lede mt-4 text-body text-muted">
          Tell it a site and run it whenever you like. Each run crawls again, compares every
          page with the run before — by content hash, then section by section — and records
          what changed with the section heading and the page. Navigation, footers, comments,
          timestamps and visitor counters are left out, so a bumped &ldquo;last updated&rdquo;
          line is not news. Every watch has a feed.
        </p>
      </header>

      <div className="max-md:mt-10 md:mt-12">
        <WatchPanel />
      </div>

      <p className="mt-8 max-w-prose text-caption text-muted">
        Nothing here runs on a schedule by itself. <code>webgraph watch run &lt;id&gt;</code>{" "}
        or <code>POST /api/watch/&#123;id&#125;/run</code> is what a cron entry or a GitHub
        Action calls; the repository ships an example workflow.
      </p>
    </main>
  );
}
