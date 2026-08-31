"use client";

import { useMemo } from "react";

import type { AnalysisEvent, Technology } from "@/lib/api";
import { percent } from "@/lib/format";

export default function TechnologyPanel({ analysis }: { analysis: AnalysisEvent }) {
  const grouped = useMemo(() => {
    const technologies = analysis.technologies ?? [];
    return technologies.reduce<Record<string, Technology[]>>((groups, technology) => {
      (groups[technology.category] ??= []).push(technology);
      return groups;
    }, {});
  }, [analysis.technologies]);

  const categories = Object.entries(grouped);

  return (
    <section className="rounded-2xl border border-line bg-surface p-6 shadow-card">
      <h2 className="text-[15px] font-extrabold tracking-tight">Technology detected</h2>

      {categories.length === 0 ? (
        <p className="mt-3 text-[13.5px] text-ink-faint">
          No technology signatures matched. The page still extracts normally.
        </p>
      ) : (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {categories.map(([category, items]) => (
            <div key={category}>
              <p className="text-[11px] font-bold uppercase tracking-[0.1em] text-ink-faint">
                {category}
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {items.map((technology) => (
                  <span
                    key={technology.name}
                    title={`${technology.evidence} · confidence ${percent(technology.confidence)}`}
                    className="inline-flex items-baseline gap-1 rounded-full border border-line bg-haze px-2.5 py-1 text-[12.5px] font-semibold"
                  >
                    {technology.name}
                    {technology.version && (
                      <em className="tabular font-mono text-[11px] not-italic text-ink-faint">
                        {technology.version}
                      </em>
                    )}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mt-5 flex flex-wrap gap-1.5 border-t border-line pt-4 text-[12px] font-semibold">
        <span className="rounded-full bg-sunk px-2.5 py-1">
          strategy <code className="font-mono">{analysis.strategy}</code>
        </span>
        <span className="rounded-full bg-sunk px-2.5 py-1">
          static coverage {percent(analysis.static_coverage)}
        </span>
        {analysis.render_required && (
          <span className="rounded-full bg-flag-warn/10 px-2.5 py-1 text-flag-warn">
            rendering required
          </span>
        )}
        {analysis.render_loses_content && (
          <span className="rounded-full bg-flag-bad/10 px-2.5 py-1 text-flag-bad">
            rendering loses content
          </span>
        )}
      </div>
    </section>
  );
}
