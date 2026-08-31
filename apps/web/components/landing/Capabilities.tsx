const CAPABILITIES: ReadonlyArray<{ title: string; body: string; detail: string }> = [
  {
    title: "Reading order, recovered",
    body:
      "Source order is not reading order. CSS reorders content freely, so a depth-first DOM " +
      "walk silently jumbles exactly the pages where sequence matters most.",
    detail:
      "Recursive XY-cut over measured bounding boxes. Where no geometry is available the engine " +
      "falls back to source order and says so, rather than presenting a guess as a measurement.",
  },
  {
    title: "Every route, not every sitemap entry",
    body:
      "A sitemap is neither complete nor current. One site advertised 4 URLs and had 75 live " +
      "pages; discovery unions the sitemap with a two-level link crawl and verifies each one.",
    detail:
      "97.7% mean route recall across 93 sites, scored against a real-browser oracle. Static " +
      "link-following alone scores 26.5% once the oracle looks two levels deep.",
  },
  {
    title: "Site chrome removed by comparison",
    body:
      "Navigation and footers repeat on every page. A single-page extractor cannot know that; " +
      "a whole-site crawler gets it free as a by-product of having crawled.",
    detail:
      "Repeated text and never-varying template slots, unioned. Precision rises with recall " +
      "unchanged — the detector does not invent chrome on a site that has none.",
  },
  {
    title: "Both fetches, merged",
    body:
      "Predicting whether a page needs a browser does not work. On the pages that measurably " +
      "lost content without rendering, prediction scored 0 out of 7.",
    detail:
      "So the engine stopped predicting. Static and rendered fetches are merged into one " +
      "document, because on the sites measured neither one alone was complete.",
  },
];

export default function Capabilities() {
  return (
    <section
      id="capabilities"
      className="mx-auto w-full max-w-6xl scroll-mt-20 px-5 py-20 sm:px-8"
    >
      <h2 className="max-w-2xl font-display text-[clamp(1.9rem,4.5vw,2.9rem)] leading-tight">
        Four decisions that came out of measurement
      </h2>
      <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-ink-soft">
        Each one replaced something that sounded reasonable and then failed a benchmark.
      </p>

      <div className="mt-10 grid gap-4 sm:grid-cols-2">
        {CAPABILITIES.map((item) => (
          <article
            key={item.title}
            className="rounded-2xl border border-line bg-surface p-6 shadow-card transition-shadow hover:shadow-lift"
          >
            <h3 className="text-[17px] font-extrabold tracking-tight">{item.title}</h3>
            <p className="mt-3 text-[14px] leading-relaxed text-ink-soft">{item.body}</p>
            <p className="mt-3 border-t border-line pt-3 text-[13px] leading-relaxed text-ink-faint">
              {item.detail}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}
