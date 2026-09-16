import type { Metadata } from "next";

import GraphWorkbench from "@/components/graph/GraphWorkbench";
import { normalizeInput } from "@/lib/url";

export const metadata: Metadata = {
  title: "WebGraph",
  description:
    "A model reads every page of a crawl and builds a cited knowledge graph of the site. Ask it a question and watch the path light up.",
  robots: { index: false },
};

/**
 * Search parameters are read here, in the server component, and handed down as props --
 * the same arrangement as `/extract`. Everything below is client-side: the API is asked for
 * the flag, the graph and the answers from the reader's browser, with the reader's key.
 */
export default async function GraphPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const raw = params.url;
  const value = Array.isArray(raw) ? raw[0] : raw;
  const normalized = value ? normalizeInput(value) : null;
  const initialUrl = normalized?.ok ? normalized.url : "";

  return (
    <main className="page-col max-md:pt-12 md:pt-20">
      <GraphWorkbench initialUrl={initialUrl} />
    </main>
  );
}
