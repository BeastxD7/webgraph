import type { Metadata } from "next";

import ReportPrompt from "@/components/report/ReportPrompt";
import ReportRun from "@/components/report/ReportRun";
import { normalizeInput } from "@/lib/url";

const DESCRIPTION =
  "What a site shows people, what it shows machines, and how ready it is for AI agents: readable without JavaScript, what robots.txt declares per bot, hidden and injected links, walls, dead links, with a suggested robots.txt and llms.txt.";

/**
 * A result page is `noindex`, like `/extract`: a crawler that runs JavaScript and indexes
 * a shared link would start a three-minute report against the site on every visit.
 */
export async function generateMetadata({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}): Promise<Metadata> {
  const params = await searchParams;
  const hasUrl = Boolean(params.url);
  return { title: "Site report", description: DESCRIPTION, ...(hasUrl ? { robots: { index: false } } : {}) };
}

/**
 * `/report?url=…` runs and shows a report; `/report` alone is the prompt. The address lives
 * in the query string so a result has a link (the `/report/[domain]` route is the short
 * form for a site's root). Search parameters are read here, in the server component, and
 * handed down as props -- the same shape as `/extract`.
 */
export default async function ReportPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const single = (key: string) => {
    const value = params[key];
    return Array.isArray(value) ? value[0] : value;
  };
  const raw = single("url") ?? "";
  const normalized = raw ? normalizeInput(raw) : null;
  const parsedPages = Number(single("pages"));
  const pages = Number.isFinite(parsedPages) && parsedPages > 0 ? Math.floor(parsedPages) : undefined;

  return (
    <main className="page-col max-md:pb-16 max-md:pt-12 md:pb-24 md:pt-20">
      <header>
        <h1 className="font-display text-h1 text-ink">Site report</h1>
        <p className="measure-lede mt-4 text-body text-muted">
          What a site shows people, what it shows machines, and how ready it is for AI agents.
          Measured, not scored by opinion: words without JavaScript against words with it, what
          robots.txt declares for each well-known bot, hidden and off-screen links, walls, dead
          links, the stack and its age. With a suggested robots.txt and llms.txt.
        </p>
      </header>

      <div className="max-md:mt-8 md:mt-10">
        <ReportPrompt initial={normalized?.ok ? normalized.url : raw} />
        {normalized && !normalized.ok && (
          <p role="alert" className="mt-2 text-caption font-medium text-bad">
            {normalized.reason}
          </p>
        )}
      </div>

      {normalized?.ok && (
        <div className="max-md:mt-10 md:mt-12">
          <ReportRun key={`${normalized.url}|${pages ?? ""}`} url={normalized.url} pages={pages} />
        </div>
      )}

      {!normalized && (
        <p className="mt-8 max-w-prose text-caption text-muted">
          The engine never impersonates other bots: every request identifies itself as webgraph
          and obeys robots.txt. The bots table is what the site&apos;s file declares for each
          name, not what that bot would be served.
        </p>
      )}
    </main>
  );
}
