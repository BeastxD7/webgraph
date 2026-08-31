const NUMBERS: ReadonlyArray<{ value: string; label: string; source: string }> = [
  { value: "97.7%", label: "mean route recall", source: "93 sites vs a real-browser oracle" },
  { value: "26.5%", label: "static-only recall", source: "the same oracle, two levels deep" },
  { value: "0/7", label: "render prediction", source: "why both fetches are merged instead" },
  { value: "132", label: "fingerprint rules", source: "across 18 technology categories" },
];

export default function Evidence() {
  return (
    <section id="evidence" className="mx-auto w-full max-w-6xl scroll-mt-20 px-5 py-20 sm:px-8">
      <div className="grid gap-10 md:grid-cols-[1fr_1.1fr] md:items-center md:gap-16">
        <div>
          <h2 className="font-display text-[clamp(1.9rem,4.5vw,2.9rem)] leading-tight">
            Every claim here is a number you can re-run
          </h2>
          <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">
            The route benchmark drives a real browser as the oracle and scores the engine against
            it. The extraction benchmark scores against a majority vote of trafilatura, readability
            and jusText. Both live in the repository.
          </p>
          <pre className="mt-6 overflow-x-auto rounded-xl border border-line bg-sunk px-4 py-3 font-mono text-[12.5px] leading-relaxed text-ink-soft">
{`make bench          # extraction quality
make bench-routes   # route discovery vs browser oracle`}
          </pre>
        </div>

        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-line bg-line">
          {NUMBERS.map((item) => (
            <div key={item.label} className="bg-surface p-6">
              <dt className="tabular font-display text-[clamp(1.8rem,5vw,2.6rem)] leading-none">
                {item.value}
              </dt>
              <dd className="mt-2 text-[13.5px] font-bold">{item.label}</dd>
              <dd className="mt-1 text-[12.5px] leading-snug text-ink-faint">{item.source}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
