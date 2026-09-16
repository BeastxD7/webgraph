import type { CSSProperties } from "react";
import Link from "next/link";

import StatTile from "@/components/ui/StatTile";
import { board, MEASURED, ROUTE_RECALL, runnerUp, selfScore } from "@/lib/benchmarks";

const WCXB = board("wcxb");
const WCEB = board("wceb");
const WCEB_CONTENT_ONLY = WCEB.entries.find(
  (entry) => entry.self && entry.name.endsWith("content only"),
);
const WCXB_MARGIN = (selfScore(WCXB) - runnerUp(WCXB).score).toFixed(3);

const idx = (i: number) => ({ "--i": i }) as CSSProperties;

const MEASURED_DAY = MEASURED.date.replace(/\s*\(.*\)$/, "");

export default function ProofStrip() {
  return (
    <section aria-labelledby="proof" className="page-col border-t border-rule max-md:py-16 md:py-24">
      <p className="story-label text-label font-bold uppercase text-muted" data-reveal>
        <span className="font-mono">04</span> · The proof
      </p>
      <h2 id="proof" className="mt-4 font-display text-h2 text-ink" data-reveal style={idx(1)}>
        What was measured
      </h2>
      <div className="mt-10 grid max-lg:gap-8 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          index={0}
          value={selfScore(WCXB).toFixed(3)}
          label="WCXB, dev split"
          source={`first of seven by ${WCXB_MARGIN} — a margin the board calls a tie`}
        />
        <StatTile
          index={1}
          value={selfScore(WCEB).toFixed(3)}
          label="WCEB, 3,985 pages"
          source={`first, content and comments joined; content alone ${WCEB_CONTENT_ONLY?.score.toFixed(3) ?? "—"}, second`}
        />
        <StatTile
          index={2}
          value={ROUTE_RECALL.engine}
          label={`route recall, ${ROUTE_RECALL.sites} sites`}
          source={`against a real-browser oracle; static link-following alone finds ${ROUTE_RECALL.static}`}
        />
        <StatTile
          index={3}
          value="0%"
          label="wrong-value rate"
          source="schema fields with no evidence return nothing; enforced by test"
        />
      </div>
      <p className="mt-8 max-w-prose text-small text-muted" data-reveal style={idx(4)}>
        Rows for this engine measured {MEASURED_DAY} on{" "}
        <code className="font-mono">main@{MEASURED.commit}</code> with the runners in{" "}
        <code className="font-mono">benchmark/</code>. Every other row is its authors&rsquo;
        published figure.{" "}
        <Link href="/benchmarks" className="font-medium text-accent-ink underline underline-offset-2">
          All boards, including the ones we lose →
        </Link>
      </p>
    </section>
  );
}
