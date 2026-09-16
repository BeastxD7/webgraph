import Link from "next/link";

import StatTile from "@/components/ui/StatTile";
import { board, MEASURED, ROUTE_RECALL, runnerUp, selfScore } from "@/lib/benchmarks";

const WCXB = board("wcxb");
const WCEB = board("wceb");
const WCEB_CONTENT_ONLY = WCEB.entries.find(
  (entry) => entry.self && entry.name.endsWith("content only"),
);
const WCXB_MARGIN = (selfScore(WCXB) - runnerUp(WCXB).score).toFixed(3);

const MEASURED_DAY = MEASURED.date.replace(/\s*\(.*\)$/, "");

export default function ProofStrip() {
  return (
    <section aria-labelledby="proof" className="page-col border-t border-rule max-md:py-16 md:py-24">
      <h2 id="proof" className="sr-only">
        What was measured
      </h2>
      <div className="grid max-lg:gap-8 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          value={selfScore(WCXB).toFixed(3)}
          label="WCXB, dev split"
          source={`first of seven by ${WCXB_MARGIN} — a margin the board calls a tie`}
        />
        <StatTile
          value={selfScore(WCEB).toFixed(3)}
          label="WCEB, 3,985 pages"
          source={`first, content and comments joined; content alone ${WCEB_CONTENT_ONLY?.score.toFixed(3) ?? "—"}, second`}
        />
        <StatTile
          value={ROUTE_RECALL.engine}
          label={`route recall, ${ROUTE_RECALL.sites} sites`}
          source={`against a real-browser oracle; static link-following alone finds ${ROUTE_RECALL.static}`}
        />
        <StatTile
          value="0%"
          label="wrong-value rate"
          source="schema fields with no evidence return nothing; enforced by test"
        />
      </div>
      <p className="mt-8 max-w-prose text-caption text-muted">
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
