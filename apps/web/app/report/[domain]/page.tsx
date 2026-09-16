import type { Metadata } from "next";
import Link from "next/link";

import ReportRun from "@/components/report/ReportRun";
import { normalizeInput } from "@/lib/url";

/** `/report/vtu.ac.in` is the report for `https://vtu.ac.in/`: the shareable short form. */
export async function generateMetadata({ params }: { params: Promise<{ domain: string }> }): Promise<Metadata> {
  const { domain } = await params;
  return { title: `Site report — ${decodeURIComponent(domain)}`, robots: { index: false } };
}

export default async function DomainReportPage({ params }: { params: Promise<{ domain: string }> }) {
  const { domain } = await params;
  const normalized = normalizeInput(decodeURIComponent(domain));

  return (
    <main className="page-col max-md:pb-16 max-md:pt-12 md:pb-24 md:pt-20">
      <p className="text-caption text-muted">
        <Link href="/report" className="text-accent-ink underline underline-offset-2">
          Site report
        </Link>{" "}
        · another site
      </p>
      {normalized.ok ? (
        <div className="mt-4">
          <ReportRun key={normalized.url} url={normalized.url} />
        </div>
      ) : (
        <p role="alert" className="mt-4 text-small text-bad">
          {normalized.reason ?? "That does not look like a web address."}
        </p>
      )}
    </main>
  );
}
