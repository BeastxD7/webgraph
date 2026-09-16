"use client";

import { useEffect, useState } from "react";

import { ApiError, api, type SiteReport } from "@/lib/api";
import { prettyUrl } from "@/lib/format";

import ReportView from "./ReportView";

type State =
  | { phase: "running" }
  | { phase: "done"; report: SiteReport }
  | { phase: "failed"; message: string };

/**
 * Runs one report and shows it. The API answers once, at the end -- a report is a few
 * pages fetched a second apart, so the wait is said out loud with the reason for it
 * rather than left as a spinner.
 */
export default function ReportRun({ url, pages }: { url: string; pages?: number }) {
  // The caller keys this component on the address, so a new address is a fresh mount and
  // the initial state is the running one; nothing needs resetting inside the effect.
  const [state, setState] = useState<State>({ phase: "running" });
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api
      .siteReport({ url, pages })
      .then((report) => {
        if (!cancelled) setState({ phase: "done", report });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const message = error instanceof ApiError ? error.message : "The report could not be run.";
        setState({ phase: "failed", message });
      });
    return () => {
      cancelled = true;
    };
  }, [url, pages]);

  useEffect(() => {
    if (state.phase !== "running") return;
    // Counted in ticks rather than against a clock read during render, which the purity
    // rule forbids; a second's drift over a few minutes is not worth the exception.
    const timer = setInterval(() => setElapsed((seconds) => seconds + 1), 1000);
    return () => clearInterval(timer);
  }, [state.phase]);

  if (state.phase === "running") {
    return (
      <section aria-live="polite" className="border-b border-rule py-10">
        <p className="flex items-center gap-3 text-body text-ink">
          <span
            aria-hidden
            className="is-running size-2 shrink-0 rounded-full bg-accent animate-[breathe_1.8s_ease-out_infinite]"
          />
          Measuring <span className="font-mono text-code">{prettyUrl(url)}</span>
          <span className="tabular text-caption text-muted">{elapsed}s</span>
        </p>
        <p className="measure-prose mt-3 text-small text-muted">
          This takes one to three minutes. The root is fetched twice, once plainly and once in
          a real browser, then up to {pages ?? 5} pages the same way, and each page&apos;s internal
          links are checked -- every request to the site a second apart, all of them identified
          as webgraph. Nothing is fetched as another bot.
        </p>
      </section>
    );
  }

  if (state.phase === "failed") {
    return (
      <section role="alert" className="border-b border-rule py-10">
        <p className="text-small font-semibold text-bad">The report could not be run.</p>
        <p className="mt-2 break-words font-mono text-code text-ink">{state.message}</p>
      </section>
    );
  }

  return <ReportView report={state.report} />;
}
