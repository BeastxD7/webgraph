import type { Metadata } from "next";

import ColumnGap from "@/components/benchmarks/ColumnGap";
import ProgressLine from "@/components/benchmarks/ProgressLine";
import RankChart from "@/components/benchmarks/RankChart";
import ScatterPlane from "@/components/benchmarks/ScatterPlane";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import { BOARDS } from "@/lib/benchmarks";

export const metadata: Metadata = {
  title: "Benchmarks",
  description:
    "Where this engine places on every public web content extraction benchmark, including the ones it loses.",
};

export default function BenchmarksPage() {
  return (
    <>
      <div className="border-b border-line bg-surface">
        <SiteHeader />
      </div>

      <main className="mx-auto w-full max-w-6xl px-5 pb-24 sm:px-8">
        <header className="max-w-3xl py-16">
          <p className="font-mono text-[12px] uppercase tracking-[0.14em] text-ink-faint">
            Measured, not claimed
          </p>
          <h1 className="mt-3 font-display text-[clamp(2.2rem,5.5vw,3.4rem)] leading-[1.08]">
            Every public benchmark, including the ones we lose
          </h1>
          <p className="mt-5 text-[15.5px] leading-relaxed text-ink-soft">
            Six boards, six different definitions of a correct extraction. This engine is third
            of seven on the widest of them and first on one corpus of 700 pages. It is also
            eighth of fourteen on the only board that scores a real fetch, and well behind the
            leader wherever tables and equations are graded on their own. All of it is below.
          </p>
        </header>

        <section className="mb-20 border-y border-line py-12">
          <div className="grid gap-8 md:grid-cols-[1fr_1.35fr] md:items-start md:gap-14">
            <div className="min-w-0">
              <h2 className="font-display text-[1.8rem] leading-tight">
                Fetching and extracting are two different problems
              </h2>
              <p className="mt-4 text-[14px] leading-relaxed text-ink-soft">
                Five of the six boards below hand every engine the same saved HTML file, so they
                measure only the second problem. This one measures both, on a thousand live
                URLs, which makes it the only place the two can be told apart.
              </p>
              <p className="mt-3 text-[14px] leading-relaxed text-ink-soft">
                Read it left to right. The distance between the clusters is what anti-bot
                infrastructure buys, and it buys pages, not quality.
              </p>
            </div>
            <div className="min-w-0">
              <ScatterPlane />
            </div>
          </div>
        </section>

        <section className="grid gap-x-12 gap-y-14 md:grid-cols-2">
          {BOARDS.map((board) => (
            <article
              key={board.id}
              id={board.id}
              className={`min-w-0 scroll-mt-20 ${board.wide ? "md:col-span-2" : ""}`}
            >
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h2 className="font-display text-[1.5rem] leading-tight">{board.name}</h2>
                <span className="font-mono text-[11.5px] text-ink-faint">{board.pages}</span>
              </div>
              <p className="mt-2 text-[13.5px] leading-relaxed text-ink-soft">{board.asks}</p>
              <p className="mt-1 font-mono text-[11.5px] text-ink-faint">{board.metric}</p>
              <div className="mt-6">
                <RankChart board={board} />
              </div>
              <p className="mt-5 border-l-2 border-clay/40 pl-3 text-[12.5px] leading-relaxed text-ink-faint">
                {board.caveat}
              </p>
            </article>
          ))}
        </section>

        <section className="mt-20 grid gap-x-12 gap-y-14 border-t border-line pt-14 md:grid-cols-2">
          <article className="min-w-0">
            <h2 className="font-display text-[1.5rem] leading-tight">Where the distance sits</h2>
            <p className="mt-2 max-w-prose text-[13.5px] leading-relaxed text-ink-soft">
              An overall score averages five columns and hides that four of them are close. The
              honest picture is per column.
            </p>
            <div className="mt-6">
              <ColumnGap />
            </div>
          </article>

          <article className="min-w-0">
            <h2 className="font-display text-[1.5rem] leading-tight">One session on WCXB</h2>
            <p className="mt-2 max-w-prose text-[13.5px] leading-relaxed text-ink-soft">
              Five fixes, each traced to a page that was being extracted wrongly, and none of
              them a tuned constant.
            </p>
            <div className="mt-6">
              <ProgressLine />
            </div>
          </article>
        </section>

        <section className="mt-20 max-w-3xl border-t border-line pt-14">
          <h2 className="font-display text-[1.6rem] leading-tight">How to read these</h2>
          <div className="mt-5 flex flex-col gap-4 text-[14px] leading-relaxed text-ink-soft">
            <p>
              Rows marked as this engine are runs of the benchmark runners in this repository,
              on one machine, against a local clone of each corpus. Every other row is the
              figure its authors published. No competing system was executed here, because a
              system run by someone who has not tuned it is not a fair comparison.
            </p>
            <p>
              Bars start at zero and rankings are never reordered. Where this engine places
              eighth it is drawn eighth.
            </p>
            <p>
              One thing none of these boards can measure: five of the six hand every extractor
              the same saved HTML file, so fetching is factored out of the result entirely. And
              every metric here is a bag of words or an edit distance over one, which cannot
              distinguish a correctly read two-column page from one read straight across,
              because both contain the same words. The engine&rsquo;s reading-order work is
              invisible to all of it, in both directions.
            </p>
          </div>
        </section>
      </main>

      <SiteFooter />
    </>
  );
}
