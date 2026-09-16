import type { StageCopy } from "./scene/scene";

/**
 * The stage before JavaScript: the scene's final frame as inline SVG, server-rendered, in the
 * same 800×600 box the canvas uses. `Stage` hides it when it can draw; without JavaScript,
 * it is the illustration. Every colour is a token, so it follows the theme like the canvas.
 */
const PAGE = { x: 150, y: 50, w: 320, h: 510 };
const L = PAGE.x + 20;
const W = PAGE.w - 40;

const BLOCKS: ReadonlyArray<{ n: number; x: number; y: number; w: number; h: number; kind: "nav" | "h1" | "text" | "image" | "table" }> = [
  { n: 1, x: L, y: 82, w: W, h: 18, kind: "nav" },
  { n: 2, x: L, y: 118, w: 210, h: 34, kind: "h1" },
  { n: 3, x: L, y: 166, w: W, h: 38, kind: "text" },
  { n: 4, x: L, y: 222, w: 128, h: 96, kind: "image" },
  { n: 5, x: L + 144, y: 222, w: W - 144, h: 96, kind: "text" },
  { n: 6, x: L, y: 336, w: W, h: 62, kind: "text" },
  { n: 7, x: L, y: 416, w: W, h: 78, kind: "table" },
  { n: 8, x: L, y: 512, w: W, h: 30, kind: "text" },
];

const MARKDOWN = [
  "## Documentation",
  "# Reading a page",
  "Point it at a website. Every public page …",
  "![figure](figure.png)",
  "Neither fetch alone is complete; …",
  "Blocks are matched by content and unioned.",
  "| board | pages | metric |",
  "Order is measured, not assumed.",
];

const NODES: ReadonlyArray<readonly [number, number, string]> = [
  [652, 358, "/"],
  [600, 318, "/docs"],
  [716, 312, "/api"],
  [742, 380, "/pricing"],
  [690, 416, "/about"],
  [612, 412, "/blog"],
];
const EDGES: ReadonlyArray<readonly [number, number]> = [[0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [1, 5], [2, 3], [4, 3]];

function Lines({ x, y, w, h }: { x: number; y: number; w: number; h: number }) {
  const n = Math.max(1, Math.floor((h + 3) / 9));
  return (
    <>
      {Array.from({ length: n }, (_, i) => (
        <rect key={i} x={x} y={y + i * 9} width={i === n - 1 ? w * 0.58 : w * (0.86 + (((i * 37) % 10) / 100) * 1.4)} height={4} rx={2} fill="var(--ink)" opacity={0.22} />
      ))}
    </>
  );
}

export default function StoryStill({ copy }: { copy: StageCopy }) {
  return (
    <svg
      viewBox="0 0 800 600"
      role="img"
      aria-label="A web page read as ordered blocks, emitted as Markdown in reading order and linked into a graph of the site; beside it, the Site Truth Report of what the site hides."
      className="absolute inset-0 size-full font-mono"
      style={{ fontSize: 10.5 }}
    >
      <rect x={PAGE.x} y={PAGE.y} width={PAGE.w} height={PAGE.h} rx={8} fill="var(--surface)" stroke="var(--rule-strong)" />
      <line x1={PAGE.x} y1={PAGE.y + 22} x2={PAGE.x + PAGE.w} y2={PAGE.y + 22} stroke="var(--rule)" />
      <text x={PAGE.x + 12} y={PAGE.y + 15} fontSize={9} fill="var(--faint)">
        example.org/docs/reading-a-page
      </text>

      {BLOCKS.map((b) => (
        <g key={b.n}>
          {b.kind === "nav" && (
            <>
              {[0, 44, 82, 132].map((dx, i) => (
                <rect key={i} x={b.x + dx} y={b.y + 4} width={[34, 28, 40, 30][i]} height={10} rx={5} fill="var(--ink)" opacity={0.22} />
              ))}
              <rect x={b.x + b.w - 42} y={b.y + 2} width={42} height={14} rx={7} fill="var(--accent)" />
            </>
          )}
          {b.kind === "h1" && (
            <>
              <rect x={b.x} y={b.y} width={b.w} height={12} rx={3} fill="var(--ink)" opacity={0.86} />
              <rect x={b.x} y={b.y + 20} width={b.w * 0.62} height={12} rx={3} fill="var(--ink)" opacity={0.86} />
            </>
          )}
          {b.kind === "text" && <Lines {...b} />}
          {b.kind === "image" && (
            <>
              <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={4} fill="var(--sunk)" />
              <polyline
                points={`${b.x + 8},${b.y + b.h - 12} ${b.x + b.w * 0.36},${b.y + b.h * 0.42} ${b.x + b.w * 0.55},${b.y + b.h * 0.66} ${b.x + b.w * 0.72},${b.y + b.h * 0.5} ${b.x + b.w - 8},${b.y + b.h - 12}`}
                fill="none"
                stroke="var(--faint)"
                strokeWidth={1.5}
              />
              <circle cx={b.x + b.w * 0.76} cy={b.y + b.h * 0.26} r={6} fill="var(--faint)" />
            </>
          )}
          {b.kind === "table" && (
            <>
              <rect x={b.x} y={b.y} width={b.w} height={16} rx={3} fill="var(--sunk)" />
              {[1, 2, 3, 4].map((r) => (
                <line key={r} x1={b.x} y1={b.y + r * 15.5} x2={b.x + b.w} y2={b.y + r * 15.5} stroke="var(--rule)" />
              ))}
              {[1, 2, 3].map((c) => (
                <line key={c} x1={b.x + (b.w / 4) * c} y1={b.y} x2={b.x + (b.w / 4) * c} y2={b.y + b.h} stroke="var(--rule)" />
              ))}
            </>
          )}
          <circle cx={b.x - 11} cy={b.y + 7} r={7} fill="var(--accent)" />
          <text x={b.x - 11} y={b.y + 10.5} fontSize={9} fontWeight={700} textAnchor="middle" fill="var(--inverse)">
            {b.n}
          </text>
        </g>
      ))}

      <rect x={520} y={30} width={256} height={22} rx={11} fill="var(--accent-soft)" />
      <circle cx={532} cy={41} r={3} fill="var(--accent)" />
      <text x={540} y={45} fontSize={9} fill="var(--accent-ink)">
        {copy.fidelity}
      </text>

      <text x={520} y={74} fontSize={9} fill="var(--faint)">
        content.md
      </text>
      {MARKDOWN.map((line, i) => (
        <g key={i}>
          <circle cx={525} cy={94 + i * 20} r={5} fill="var(--accent)" />
          <text x={525} y={97 + i * 20} fontSize={7.5} fontWeight={700} textAnchor="middle" fill="var(--inverse)">
            {i + 1}
          </text>
          <text x={536} y={98 + i * 20} fontSize={11} fill={line.startsWith("#") ? "var(--ink)" : "var(--muted)"}>
            {line}
          </text>
        </g>
      ))}

      {EDGES.map(([a, b], i) => {
        const na = NODES[a];
        const nb = NODES[b];
        if (!na || !nb) return null;
        return <line key={i} x1={na[0]} y1={na[1]} x2={nb[0]} y2={nb[1]} stroke="var(--accent)" opacity={0.45} />;
      })}
      {NODES.map(([x, y, label], i) => (
        <g key={label}>
          <circle cx={x} cy={y} r={i === 0 ? 15 : 10} fill="var(--accent)" opacity={0.18} />
          <circle cx={x} cy={y} r={i === 0 ? 7 : 4.5} fill={i === 0 ? "var(--accent)" : "var(--surface)"} stroke="var(--accent)" strokeWidth={1.5} />
          <text x={x + (i === 0 ? 11 : 8.5)} y={y + 3} fontSize={8.5} fill="var(--muted)">
            {label}
          </text>
        </g>
      ))}

      {/* An SVG anchor, not next/link: this is the no-JavaScript frame, inside inline SVG,
          where `<Link>` cannot render; a full navigation is what it should do. */}
      {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
      <a href="/report" aria-label="Site Truth Report — run it on any site">
      <rect x={520} y={428} width={260} height={126} rx={6} fill="var(--surface)" stroke="var(--rule-strong)" />
      <text x={534} y={448} fontSize={8} fontWeight={700} fill="var(--muted)" className="font-sans">
        SITE TRUTH REPORT · /report
      </text>
      <text x={534} y={466} fontSize={12} fontWeight={700} fill="var(--ink)" className="font-sans">
        what the site hides
      </text>
      <text x={766} y={466} fontSize={9} fontWeight={600} textAnchor="end" fill="var(--accent-ink)" className="font-sans">
        run it on any site →
      </text>
      {copy.report.map(([label, value], i) => (
        <g key={label}>
          <text x={534} y={488 + i * 21} fontSize={9} fontWeight={600} fill="var(--muted)" className="font-sans">
            {label}
          </text>
          <text x={766} y={488 + i * 21} fontSize={9} textAnchor="end" fill="var(--ink)">
            {value}
          </text>
          <line x1={534} y1={495 + i * 21} x2={766} y2={495 + i * 21} stroke="var(--rule)" />
        </g>
      ))}
      </a>
    </svg>
  );
}
