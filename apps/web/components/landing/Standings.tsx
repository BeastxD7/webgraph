import type { CSSProperties } from "react";
import Link from "next/link";

import { board, leaderScore, runnerUp, selfScore, WCXB_TEST } from "@/lib/benchmarks";

/**
 * Five boards in one table, this engine's row against the leader's, with the place said in
 * words. The self column is marked by a rule-strong edge, not a colour: the same form for a
 * first and a tenth (DESIGN.md §1.4). Every score is read from `lib/benchmarks.ts`.
 *
 * Under each score a 2px bar draws the engine's share of the leader's score when the row
 * scrolls into view — full for a first place, 0.78 of the track for WebMainBench — so a loss
 * is drawn with exactly the form of a win.
 */
const idx = (i: number) => ({ "--i": i }) as CSSProperties;

const WCXB_RUNNER_UP = runnerUp(board("wcxb"));

const ROWS: ReadonlyArray<{ id: string; label: string; pages: string; place: string }> = [
  {
    id: "wcxb",
    label: "WCXB (dev)",
    pages: "1,497",
    place: `1st of 7 (tie: ${WCXB_RUNNER_UP.name} ${WCXB_RUNNER_UP.score.toFixed(3)})`,
  },
  { id: "wceb", label: "WCEB", pages: "3,985", place: "1st of 7 systems, content + comments" },
  { id: "zyte", label: "Zyte article", pages: "181", place: "10th of 35" },
  {
    id: "webmainbench",
    label: "WebMainBench",
    pages: "545",
    place: "2nd of 6 (column mean; overall 0.733, tables 0.395)",
  },
  {
    id: "scrape-evals",
    label: "scrape-evals",
    pages: "1,000 live",
    place: "not a ranking: different day, no proxy",
  },
];

export default function Standings() {
  return (
    <section aria-labelledby="standings" className="page-col border-t border-rule max-md:py-16 md:py-24">
      <h2 id="standings" className="font-display text-h2 text-ink" data-reveal>
        Where it stands, including where it does not
      </h2>

      <div className="mt-8 overflow-x-auto">
        <table className="w-full min-w-[40rem] border-collapse text-small">
          <thead>
            <tr className="border-b border-rule text-left text-label font-bold uppercase text-muted">
              <th scope="col" className="py-2.5 pr-4 font-bold">
                board
              </th>
              <th scope="col" className="tabular py-2.5 pr-4 text-right font-bold">
                pages
              </th>
              <th scope="col" className="py-2.5 pr-4 font-bold">
                metric
              </th>
              <th
                scope="col"
                className="tabular py-2.5 pl-3 pr-4 text-right font-bold text-ink shadow-[inset_2px_0_0_var(--rule-strong)]"
              >
                webgraph
              </th>
              <th scope="col" className="tabular py-2.5 pr-4 text-right font-bold">
                leader
              </th>
              <th scope="col" className="py-2.5 font-bold">
                place
              </th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row, i) => {
              const data = board(row.id);
              const share = Math.min(1, selfScore(data) / leaderScore(data));
              return (
                <tr key={row.id} className="border-b border-rule" data-reveal style={idx(i)}>
                  <th
                    scope="row"
                    className="py-3 pr-4 text-left font-semibold text-ink"
                  >
                    <Link href={`/benchmarks#${data.id}`} className="hover:text-accent-ink">
                      {row.label}
                    </Link>
                  </th>
                  <td className="tabular py-3 pr-4 text-right text-ink">{row.pages}</td>
                  <td className="py-3 pr-4 text-muted">{data.metric}</td>
                  <td className="tabular py-3 pl-3 pr-4 text-right font-semibold text-ink shadow-[inset_2px_0_0_var(--rule-strong)]">
                    {selfScore(data).toFixed(3)}
                    <span className="mt-1.5 block h-0.5 w-full bg-rule" aria-hidden>
                      <span
                        className="score-bar block h-full bg-accent"
                        style={{ "--v": share.toFixed(3) } as CSSProperties}
                      />
                    </span>
                  </td>
                  <td className="tabular py-3 pr-4 text-right text-ink">
                    {leaderScore(data).toFixed(3)}
                  </td>
                  <td className="py-3 text-muted">{row.place}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-6 max-w-prose text-small text-muted" data-reveal style={idx(5)}>
        On the held-out WCXB test split ({WCXB_TEST.pages} pages) this engine scores{" "}
        {WCXB_TEST.us}; {WCXB_TEST.rival}&rsquo;s author reports {WCXB_TEST.rivalScore} there.{" "}
        <Link href="/benchmarks" className="font-medium text-accent-ink underline underline-offset-2">
          Read every board →
        </Link>
      </p>
    </section>
  );
}
