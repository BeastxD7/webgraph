import type { Metadata } from "next";
import Link from "next/link";

import StageList from "@/components/pipeline/StageList";
import { PRINCIPLES, STAGES } from "@/lib/pipeline";

export const metadata: Metadata = {
  title: "How it works",
  description:
    "You hand the engine one address. Every stage that follows, what it produces, and what it does when something goes wrong.",
};

export default function HowItWorksPage() {
  return (
    <>
      <main className="mx-auto w-full max-w-5xl px-5 pb-24 sm:px-8">
        <header className="max-w-3xl py-16">
          <p className="font-mono text-[12px] uppercase tracking-[0.14em] text-ink-faint">
            Engine walkthrough
          </p>
          <h1 className="mt-3 font-display text-[clamp(2.1rem,5.5vw,3.3rem)] leading-[1.08]">
            You hand it one address. Here is everything that happens next.
          </h1>
          <p className="mt-5 text-[15.5px] leading-relaxed text-ink-soft">
            Nine stages, in the order they run, with what each one produces and what it does
            when something goes wrong. The failure paths are not an appendix: on a crawl of
            thousands of pages they are most of the engineering. Every figure below comes from
            a benchmark run or a diagnostic in the repository.
          </p>

          <nav aria-label="Stages" className="mt-8 flex flex-wrap gap-x-2 gap-y-2">
            {STAGES.map((stage, index) => (
              <a
                key={stage.id}
                href={`#${stage.id}`}
                className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 text-caption text-ink-soft transition-colors hover:border-leaf-300 hover:text-ink pointer-coarse:min-h-10"
              >
                <span className="font-mono text-[11px] text-ink-faint">
                  {String(index + 1).padStart(2, "0")}
                </span>
                {stage.title.split(",")[0]}
              </a>
            ))}
          </nav>
        </header>

        <StageList />

        <section className="mt-20 max-w-3xl border-t border-line pt-14">
          <h2 className="font-display text-[1.7rem] leading-tight">
            The two ideas everything else follows from
          </h2>
          <div className="mt-6 grid gap-6 sm:grid-cols-2">
            {PRINCIPLES.map((principle) => (
              <div key={principle.title} className="rounded-2xl border border-line bg-surface p-5 shadow-card">
                <h3 className="text-[15px] font-bold leading-snug">{principle.title}</h3>
                <p className="mt-2 text-small leading-relaxed text-ink-soft">
                  {principle.body}
                </p>
              </div>
            ))}
          </div>
          <p className="mt-8 text-small leading-relaxed text-ink-soft">
            Where the engine places against every public benchmark, including the ones it
            loses, is on the{" "}
            <Link href="/benchmarks" className="font-semibold text-leaf-700 underline underline-offset-2">
              benchmarks page
            </Link>
            .
          </p>
        </section>
      </main>

    </>
  );
}
