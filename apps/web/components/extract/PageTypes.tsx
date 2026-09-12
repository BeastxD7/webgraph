"use client";

/**
 * What the site is made of, as the classifier decides it page by page.
 *
 * A crawl of a hundred pages is hard to picture. A tally of the kinds of page found is the
 * shortest true description of a site: mostly articles with a few listings is a blog; mostly
 * products is a shop. It also makes the model's work visible, which is otherwise invisible
 * -- the type is chosen for every page and until now nothing said so.
 *
 * `unknown` is shown rather than hidden. It means the classifier was not confident enough to
 * commit, which is a real answer and the one that keeps the default extraction behaviour.
 */
const LABEL: Record<string, string> = {
  article: "Articles",
  listing: "Listings",
  collection: "Collections",
  product: "Products",
  forum: "Forums",
  documentation: "Documentation",
  service: "Service pages",
  unknown: "Not confident",
};

export default function PageTypes({
  types,
  total,
}: {
  types: Record<string, number>;
  total: number;
}) {
  const rows = Object.entries(types)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);

  if (rows.length === 0) return null;

  return (
    <div className="mt-3 rounded-lg border border-line bg-surface p-3">
      <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-faint">
        what this site is made of
      </p>
      <ul className="mt-2 flex flex-col gap-1.5">
        {rows.map(([type, count]) => (
          <li key={type} className="grid grid-cols-[minmax(0,8rem)_1fr_2.4rem] items-center gap-2">
            <span
              className={`truncate text-[12px] ${
                type === "unknown" ? "text-ink-faint italic" : "font-semibold"
              }`}
            >
              {LABEL[type] ?? type}
            </span>
            <span className="h-1.5 overflow-hidden rounded-full bg-sunk">
              <span
                className={`block h-full rounded-full ${
                  type === "unknown" ? "bg-ink-faint/40" : "bg-leaf-500"
                }`}
                style={{ width: `${(count / Math.max(total, 1)) * 100}%` }}
              />
            </span>
            <span className="tabular text-right font-mono text-[11.5px] text-ink-soft">{count}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
