const STAGES: ReadonlyArray<{ title: string; body: string; note: string }> = [
  {
    title: "Detect the stack",
    body:
      "Fingerprints markup, response headers and runtime JavaScript globals against 132 rules " +
      "across 18 categories, then measures how much of the page survives without a browser.",
    note: "Host rules are anchored to src/href, so a page that merely documents a framework is not mistaken for one built with it.",
  },
  {
    title: "Enumerate the routes",
    body:
      "Robots and sitemaps seed a frontier that a two-level link crawl extends. Every candidate " +
      "is verified live, and redirects are resolved before scoping so a moved root does not end the crawl.",
    note: "Unlimited by default. If a site has 19,999 pages, the frontier keeps going until it is exhausted.",
  },
  {
    title: "Extract each page",
    body:
      "Headings, lists, tables, code fences, images and inline links become Markdown, ordered by " +
      "geometry. Chrome detected across the corpus is offered as a separate content-only view.",
    note: "Results stream as they land, so a large crawl is readable long before it finishes.",
  },
];

export default function Pipeline() {
  return (
    <section id="pipeline" className="scroll-mt-20 border-y border-line bg-surface">
      <div className="mx-auto w-full max-w-6xl px-5 py-20 sm:px-8">
        <h2 className="max-w-2xl font-display text-[clamp(1.9rem,4.5vw,2.9rem)] leading-tight">
          Three stages, in order
        </h2>

        <ol className="mt-10 grid gap-10 md:grid-cols-3 md:gap-8">
          {STAGES.map((stage, index) => (
            <li key={stage.title} className="relative">
              <span className="font-mono text-[12px] font-medium tracking-widest text-leaf-600">
                {String(index + 1).padStart(2, "0")}
              </span>
              <h3 className="mt-2 text-[19px] font-extrabold tracking-tight">{stage.title}</h3>
              <p className="mt-3 text-[14px] leading-relaxed text-ink-soft">{stage.body}</p>
              <p className="mt-3 text-[13px] leading-relaxed text-ink-faint">{stage.note}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
