"use client";

import { useMemo, useState } from "react";

import type { PageEvent } from "@/lib/api";

type Origin = { foundOn: string | null; depth: number; via: "seed" | "sitemap" | "link" | "common-crawl" };

/**
 * The site as the crawl found it: a tree from the root, one level per link away.
 *
 * Depth 0 is the address given. Depth 1 is everything the root links to and everything its
 * sitemap lists. Depth 2 is what those pages link to, and so on. The crawl is breadth-first,
 * so a level fills completely before the next one starts, and the per-depth bar at the top
 * shows that happening.
 *
 * Each node is a page the crawl accepted, under the page that first linked to it. A page
 * linked from twenty places appears once, under the first; that is the frontier's rule and
 * the tree draws what the frontier did rather than a prettier fiction.
 *
 * Under a page, after its child pages, come the addresses it points at that the crawl did
 * not follow: links to other sites, and -- for a page that draws its content in a canvas --
 * the addresses its scripts hold. Dimmed, tagged, never counted in a depth: the tree shows
 * every address the site carries, and says which of them are pages of it.
 */
export default function DepthTree({
  root,
  origins,
  depthCounts,
  pages,
  cap,
}: {
  root: string | null;
  origins: Record<string, Origin>;
  depthCounts: Record<string, number>;
  pages: PageEvent[];
  cap: number;
}) {
  const status = useMemo(() => {
    const map = new Map<string, PageEvent>();
    for (const page of pages) map.set(page.url, page);
    return map;
  }, [pages]);

  const children = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const [url, origin] of Object.entries(origins)) {
      if (origin.foundOn === null) continue;
      const list = map.get(origin.foundOn) ?? [];
      list.push(url);
      map.set(origin.foundOn, list);
    }
    return map;
  }, [origins]);

  const depths = Object.entries(depthCounts)
    .map(([depth, count]) => [Number(depth), count] as const)
    .sort((a, b) => a[0] - b[0]);
  const largest = Math.max(1, ...depths.map(([, n]) => n));
  const extractedAt = useMemo(() => {
    const counts: Record<number, number> = {};
    for (const page of pages) {
      const depth = page.depth ?? origins[page.url]?.depth ?? 0;
      counts[depth] = (counts[depth] ?? 0) + 1;
    }
    return counts;
  }, [pages, origins]);

  if (!root) {
    return (
      <p className="rounded-2xl border border-line bg-surface px-5 py-8 text-center text-[13.5px] text-ink-faint">
        The tree appears once the root has been read.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-line bg-surface p-5 shadow-card">
        <h2 className="text-[15px] font-extrabold tracking-tight">Pages by depth</h2>
        <p className="mt-1 text-[12.5px] text-ink-faint">
          How many addresses the crawl accepted at each link distance from the root, and how
          many of those it has extracted so far.
          {cap > 0 && ` The page cap is ${cap}, so deeper levels may be known and never fetched.`}
        </p>
        <dl className="mt-4 space-y-2">
          {depths.map(([depth, count]) => {
            const done = extractedAt[depth] ?? 0;
            return (
              <div key={depth} className="grid grid-cols-[4.5rem_1fr_9rem] items-center gap-3">
                <dt className="font-mono text-[12px] text-ink-soft">depth {depth}</dt>
                <dd className="relative h-3 overflow-hidden rounded-full bg-sunk">
                  <div className="absolute inset-y-0 left-0 rounded-full bg-leaf-200" style={{ width: `${(count / largest) * 100}%` }} />
                  <div className="absolute inset-y-0 left-0 rounded-full bg-leaf-600" style={{ width: `${(done / largest) * 100}%` }} />
                </dd>
                <dd className="tabular text-right font-mono text-[12px] text-ink-soft">
                  {done.toLocaleString("en-US")} of {count.toLocaleString("en-US")}
                </dd>
              </div>
            );
          })}
        </dl>
      </section>

      <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
        <header className="border-b border-line px-4 py-3">
          <h2 className="text-[15px] font-extrabold tracking-tight">Discovery tree</h2>
          <p className="mt-0.5 text-[12.5px] text-ink-faint">
            Each page under the page that first linked to it. Open a level to see what it led to.
            Depth is <em>links from the root</em>, not path segments: <code className="font-mono">d1</code> is one click
            away wherever its address sits. The path&apos;s own depth is shown after it when the two differ.
          </p>
        </header>
        <div className="max-h-[40rem] overflow-auto px-3 py-2 font-mono text-[12px]">
          <Node url={root} depth={0} childrenOf={children} status={status} origins={origins} open />
        </div>
      </section>
    </div>
  );
}

/** Addresses the crawl did not follow, shown under a page: at most this many of each kind. */
const LEAF_LIMIT = 12;

const PAGE_SIZE = 50;

function Node({
  url,
  depth,
  childrenOf,
  status,
  origins,
  open = false,
}: {
  url: string;
  depth: number;
  childrenOf: Map<string, string[]>;
  status: Map<string, PageEvent>;
  origins: Record<string, Origin>;
  open?: boolean;
}) {
  const [expanded, setExpanded] = useState(open);
  const [shown, setShown] = useState(PAGE_SIZE);
  const kids = childrenOf.get(url) ?? [];
  const page = status.get(url);
  const via = origins[url]?.via;
  const leaves = (page?.links_out?.external.length ?? 0) + (page?.links_out?.in_script.length ?? 0);

  const state = page ? (page.ok ? "ok" : "failed") : "queued";
  const dot = state === "ok" ? "bg-leaf-600" : state === "failed" ? "bg-flag-bad" : "border border-line-strong bg-transparent";
  const label = url.replace(/^https?:\/\/[^/]+/, "") || "/";
  // Path segments, the depth Firecrawl and crawl4ai users count in. Shown beside the link
  // distance when they differ, so a reader coming from those tools is not misled by ours.
  const pathDepth = label.split("/").filter(Boolean).length;
  const host = depth === 0 ? url.replace(/^https?:\/\//, "").split("/")[0] : "";

  return (
    <div>
      <div className="flex items-center gap-2 py-1" style={{ paddingLeft: `${depth * 1.25}rem` }}>
        {kids.length > 0 || leaves > 0 ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="grid size-4 shrink-0 place-items-center rounded text-[9px] text-ink-faint hover:bg-haze"
          >
            <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>▶</span>
          </button>
        ) : (
          <span className="size-4 shrink-0" />
        )}
        <span aria-hidden className={`size-2 shrink-0 rounded-full ${dot}`} title={state} />
        <span className="shrink-0 rounded bg-sunk px-1 text-[10px] text-ink-faint" title={`${depth} ${depth === 1 ? "link" : "links"} from the root`}>d{depth}</span>
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className={`truncate ${state === "queued" ? "text-ink-faint" : "text-ink-soft hover:text-ink hover:underline"}`}
          title={url}
        >
          {host || label}
        </a>
        {pathDepth !== depth && depth > 0 && (
          <span className="shrink-0 text-[10px] text-ink-faint" title="Segments in the address's path -- how other crawlers count depth">
            /{pathDepth}
          </span>
        )}
        {via === "sitemap" && <span className="shrink-0 text-[10px] text-ink-faint">sitemap</span>}
        {via === "common-crawl" && <span className="shrink-0 text-[10px] text-ink-faint">common crawl</span>}
        {(kids.length > 0 || leaves > 0) && (
          <span className="tabular ml-auto shrink-0 text-[11px] text-ink-faint">
            {kids.length > 0 && `${kids.length.toLocaleString("en-US")} found here`}
            {kids.length > 0 && leaves > 0 && " · "}
            {leaves > 0 && `${leaves.toLocaleString("en-US")} elsewhere`}
          </span>
        )}
      </div>
      {expanded &&
        kids.slice(0, shown).map((child) => (
          <Node key={child} url={child} depth={depth + 1} childrenOf={childrenOf} status={status} origins={origins} />
        ))}
      {expanded && page?.links_out && (
        <>
          {page.links_out.external.slice(0, LEAF_LIMIT).map((l) => (
            <Leaf key={`ext-${l.url}`} url={l.url} depth={depth + 1} tag="other site" note={l.anchor} />
          ))}
          {page.links_out.in_script.slice(0, LEAF_LIMIT).map((l) => (
            <Leaf key={`js-${l.url}`} url={l.url} depth={depth + 1} tag="in script" note={l.key} />
          ))}
        </>
      )}
      {expanded && kids.length > shown && (
        <button
          type="button"
          onClick={() => setShown((n) => n + PAGE_SIZE * 4)}
          className="py-1 text-[11.5px] font-semibold text-leaf-700 underline underline-offset-2"
          style={{ paddingLeft: `${(depth + 1) * 1.25 + 1.5}rem` }}
        >
          show {Math.min(PAGE_SIZE * 4, kids.length - shown).toLocaleString("en-US")} more of {kids.length.toLocaleString("en-US")}
        </button>
      )}
    </div>
  );
}

/** An address under a page that is not a page of this site: a link to another site, or an
 * address the page's script holds. No dot, no depth badge -- it was never in the frontier. */
function Leaf({ url, depth, tag, note }: { url: string; depth: number; tag: string; note: string }) {
  return (
    <div className="flex items-center gap-2 py-0.5 text-[12.5px]" style={{ paddingLeft: `${depth * 1.25}rem` }}>
      <span className="size-4 shrink-0" />
      <span aria-hidden className="size-2 shrink-0 rounded-full border border-dashed border-line-strong" />
      <span className="shrink-0 rounded bg-sunk px-1 text-[10px] text-ink-faint">{tag}</span>
      <a href={url} target="_blank" rel="noreferrer" className="truncate text-ink-faint hover:text-ink hover:underline" title={url}>
        {url.replace(/^https?:\/\//, "").replace(/^www\./, "")}
      </a>
      {note && <span className="shrink-0 truncate text-[10.5px] text-ink-faint">{note.slice(0, 40)}</span>}
    </div>
  );
}
