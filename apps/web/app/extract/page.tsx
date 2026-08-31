import type { Metadata } from "next";
import Link from "next/link";

import RunBanner from "@/components/extract/RunBanner";
import SingleServerRun from "@/components/extract/SinglePageRun";
import SiteRun from "@/components/extract/SiteRun";
import SiteFooter from "@/components/site/SiteFooter";
import { normalizeInput } from "@/lib/url";

export const metadata: Metadata = {
  title: "Extracting",
  robots: { index: false },
};

/**
 * Search parameters are read here, in the server component, and handed down as props.
 * Reading them from a client hook instead would require a Suspense boundary and would
 * defer the whole run behind a client render for no benefit.
 */
export default async function ExtractPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const single = (key: string) => {
    const value = params[key];
    return Array.isArray(value) ? value[0] : value;
  };

  const normalized = normalizeInput(single("url") ?? "");
  const mode = single("mode") === "page" ? "page" : "site";
  const complete = single("complete") !== "false";
  const parsedMax = Number(single("max"));
  const maxPages = Number.isFinite(parsedMax) && parsedMax > 0 ? Math.floor(parsedMax) : 0;

  if (!normalized.ok) {
    return (
      <>
        <RunBanner url="nothing to extract" mode="site" />
        <div className="mx-auto w-full max-w-6xl px-5 pb-20 sm:px-8">
          <p className="rounded-2xl border border-line bg-surface px-5 py-6 text-[14px] text-ink-soft">
            {normalized.reason ?? "No website address was supplied."}{" "}
            <Link href="/#start" className="font-semibold text-leaf-700 underline underline-offset-2">
              Start from the home page
            </Link>
            .
          </p>
        </div>
        <SiteFooter />
      </>
    );
  }

  return (
    <>
      <RunBanner url={normalized.url} mode={mode} />

      <main className="pt-2">
        {mode === "site" ? (
          <SiteRun
            key={`${normalized.url}|${complete}|${maxPages}`}
            url={normalized.url}
            complete={complete}
            maxPages={maxPages}
          />
        ) : (
          <SingleServerRun key={normalized.url} url={normalized.url} />
        )}
      </main>

      <SiteFooter />
    </>
  );
}
