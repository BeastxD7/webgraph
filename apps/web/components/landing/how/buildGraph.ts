/**
 * Step 5 ("build the graph") on one clock, in ms. The pages from the crawl settle as
 * nodes and their structure draws between them; then the links the pages actually carry
 * -- across the tree, not just down it -- draw as a second kind of edge; then each page's
 * sections hang off it; and last an entity the pages name, carrying its schema.org
 * identity, appears with an edge from every page that mentions it. Nothing here is
 * inferred: the site already is a graph. `buildGraphCss` turns it into `@keyframes` text.
 *
 * Geometry is in a 576×384 box -- the stage's size in px at full width, so a 1.5 stroke
 * is 1.5px -- with node positions as percentages of it so the HTML nodes and the SVG
 * edges (`preserveAspectRatio="none"`) stay aligned however the stage is sized.
 */

import { keyframesFor } from "./timeline";

export const GRAPH_MS = {
  pagesStart: 0,
  pageStagger: 220,
  pageMs: 260,
  treeEdgeLead: 180, // an edge starts drawing this long before its child pops

  linksStart: 1500,
  linkStagger: 260,
  linkMs: 380,

  sectionsStart: 2600,
  sectionStagger: 170,
  sectionMs: 240,

  entityIn: 3800,
  entitySettled: 4100,
  badgeIn: 4150,
  entityEdgesStart: 4300,
  entityEdgeStagger: 240,
  entityEdgeMs: 360,

  captionIn: 5300,
  captionSettled: 5550,

  holdEnd: 7400,
  fadeEnd: 7800,
  cycle: 8000,
} as const;

export interface GNode { id: string; label: string; x: number; y: number; parent?: string }

/** The pages, in the order the crawl found them (root first, breadth-first). */
export const PAGES: readonly GNode[] = [
  { id: "home", label: "webgraph.com", x: 288, y: 44 },
  { id: "about", label: "/about", x: 100, y: 138, parent: "home" },
  { id: "products", label: "/products", x: 288, y: 138, parent: "home" },
  { id: "docs", label: "/docs", x: 476, y: 138, parent: "home" },
  { id: "api", label: "/docs/api", x: 420, y: 224, parent: "docs" },
];

/** Links the pages carry to each other, across the tree. */
export const LINKS: ReadonlyArray<{ from: string; to: string }> = [
  { from: "about", to: "products" },
  { from: "products", to: "api" },
  { from: "docs", to: "products" },
];

/** Sections inside pages: a page's headings, hung off it. */
export const SECTIONS: readonly GNode[] = [
  { id: "team", label: "Team", x: 100, y: 224, parent: "about" },
  { id: "pricing", label: "Pricing", x: 224, y: 224, parent: "products" },
  { id: "faq", label: "FAQ", x: 318, y: 224, parent: "products" },
  { id: "install", label: "Install", x: 532, y: 224, parent: "docs" },
];

/** The entity the pages name, and which of them mention it. */
export const ENTITY = { id: "org", label: "WebGraph Inc.", type: "schema.org/Organization", x: 288, y: 318 } as const;
export const MENTIONS = ["about", "team", "pricing", "faq"] as const;

export const BOX = { w: 576, h: 384 } as const;

export const allNodes = (): readonly GNode[] => [...PAGES, ...SECTIONS, { id: ENTITY.id, label: ENTITY.label, x: ENTITY.x, y: ENTITY.y }];
export const nodeAt = (id: string): GNode => {
  const n = allNodes().find((x) => x.id === id);
  if (!n) throw new Error(`no node ${id}`);
  return n;
};

/** A gently curved edge between two node centers. */
export const edgePath = (a: GNode, b: GNode) => {
  const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
  const dx = b.x - a.x, dy = b.y - a.y;
  // Bow perpendicular to the line, a little, so parallel edges read apart.
  const bow = Math.min(18, Math.hypot(dx, dy) * 0.12);
  const nx = -dy / (Math.hypot(dx, dy) || 1), ny = dx / (Math.hypot(dx, dy) || 1);
  return `M${a.x},${a.y} Q${mx + nx * bow},${my + ny * bow} ${b.x},${b.y}`;
};

export const pageAt = (i: number) => GRAPH_MS.pagesStart + i * GRAPH_MS.pageStagger;
export const linkAt = (i: number) => GRAPH_MS.linksStart + i * GRAPH_MS.linkStagger;
export const sectionAt = (i: number) => GRAPH_MS.sectionsStart + i * GRAPH_MS.sectionStagger;
export const mentionAt = (i: number) => GRAPH_MS.entityEdgesStart + i * GRAPH_MS.entityEdgeStagger;

export function buildGraphCss(): string {
  const M = GRAPH_MS;
  const kf = keyframesFor(M.cycle);
  const out: string[] = [];
  const gone = "opacity: 0;";
  const pop = (name: string, at: number, ms: number) => kf(name, [
    [[0, at], "opacity: 0; transform: translate(-50%, -50%) scale(0.6);"],
    [at + ms * 0.6, "opacity: 1; transform: translate(-50%, -50%) scale(1.08);"],
    [at + ms, "opacity: 1; transform: translate(-50%, -50%) scale(1);"],
    [M.holdEnd, "opacity: 1; transform: translate(-50%, -50%) scale(1);"],
    [M.fadeEnd, "opacity: 0; transform: translate(-50%, -50%) scale(0.9);"],
  ]);
  // Hidden until it starts: a fully-offset dash still shows its round cap as a dot.
  const draw = (name: string, at: number, ms: number) => kf(name, [
    [[0, at], "stroke-dashoffset: 1; opacity: 0;"],
    [at + 1, "stroke-dashoffset: 1; opacity: 1;"],
    [at + ms, "stroke-dashoffset: 0; opacity: 1;"],
    [M.holdEnd, "stroke-dashoffset: 0; opacity: 1;"],
    [M.fadeEnd, "stroke-dashoffset: 0; opacity: 0;"],
  ]);

  PAGES.forEach((p, i) => {
    out.push(pop(`graph-node-${p.id}`, pageAt(i), M.pageMs));
    if (p.parent) out.push(draw(`graph-tree-${p.id}`, pageAt(i) - M.treeEdgeLead, M.treeEdgeLead + M.pageMs * 0.5));
  });
  LINKS.forEach((l, i) => out.push(draw(`graph-link-${l.from}-${l.to}`, linkAt(i), M.linkMs)));
  SECTIONS.forEach((s, i) => {
    out.push(pop(`graph-node-${s.id}`, sectionAt(i), M.sectionMs));
    out.push(draw(`graph-tree-${s.id}`, sectionAt(i) - 100, M.sectionMs));
  });
  out.push(pop(`graph-node-${ENTITY.id}`, M.entityIn, M.entitySettled - M.entityIn));
  out.push(kf("graph-badge", [
    [[0, M.badgeIn], "opacity: 0; transform: translateX(-50%) translateY(4px);"],
    [M.badgeIn + 220, "opacity: 1; transform: translateX(-50%) translateY(0);"],
  ]));
  MENTIONS.forEach((id, i) => out.push(draw(`graph-mention-${id}`, mentionAt(i), M.entityEdgeMs)));
  // The ping on the entity as its first mention lands.
  out.push(kf("graph-ping", [
    [[0, M.entityEdgesStart], "opacity: 0; transform: scale(1);"],
    [M.entityEdgesStart + 1, "opacity: 0.5; transform: scale(1);"],
    [M.entityEdgesStart + 700, "opacity: 0; transform: scale(1.8);"],
  ]));
  out.push(kf("graph-caption", [
    [[0, M.captionIn], "opacity: 0; transform: translateX(-50%) translateY(6px);"],
    [M.captionSettled, "opacity: 1; transform: translateX(-50%) translateY(0);"],
    [M.holdEnd, "opacity: 1; transform: translateX(-50%) translateY(0);"],
    [M.fadeEnd, gone],
  ]));
  return out.join("\n");
}
