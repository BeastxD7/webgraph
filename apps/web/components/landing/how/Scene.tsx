import type { CSSProperties, ReactNode } from "react";

import { floor, poly, pt, wall } from "./iso";

/**
 * The illustration beside the five steps: a site's pages fanning out, one page fetched
 * twice and merged, its hidden parts lifted away, cut into reading order and written as
 * Markdown, then linked into a graph. Server-rendered inline SVG; the stylesheet
 * (how.css) does the assembling, the step cross-morph and the reduced-motion still,
 * keyed on the stage's `data-in` and `data-step`, written by `HowMotion` from scroll
 * progress along the curved path beside it.
 *
 * Step 1 (discover the pages) is not drawn here at all -- it's a separate flat overlay,
 * `Step1Intro.tsx`, shown in place of this scene while `data-step="1"`; see `HowMotion.tsx`.
 *
 * Classes: `.rise` assembles on enter (stagger `--i`); `.s2..s5` belong to one step; `.core`
 * is the one page shared by fetch/refuse/reading-order, absent for the graph (the scene has
 * zoomed out past any one page by step 5); `.hid` lifts off and dissolves in step 3, then
 * keeps a slow drift once it dissolves; `.draw` is a mask stroke that draws a path; `.dots`
 * marches; `.cut` draws in step 4; `.pop` scales in; `.glow` (step 2) is a quiet pulse
 * behind the assembled page's "union" tag; `.cursor` (step 4) blinks at the end of the
 * Markdown's last written line; `.graph-dot` (step 5) travels the real link edges. Every
 * one of those is a plain, always-running CSS animation once its step is active -- the
 * point is that nothing here ever finishes and holds still. A group that the stylesheet
 * transforms never carries an attribute transform of its own (CSS would replace it).
 */
const W = 200; // the page, in world units
const H = 236;

/** The Markdown sheet's placement; its rows get numbers beside them in screen space. */
const MD = { x: 246, y: -70, top: 224, w: 150, h: 200 } as const;

const i = (n: number) => ({ "--i": n }) as CSSProperties;

/** Screen point of a local (u, v) on the page. */
const onPage = (u: number, v: number) => pt(u, 0, H - v);
/** Screen point beside row `v` of the Markdown sheet: level with its text, 14px to the left. */
const onMd = (v: number): readonly [number, number] => {
  const [x, y] = pt(MD.x + 10, MD.y, MD.top - v);
  return [x - 14, y];
};

/** The page's blocks in reading order: where each sits on the page and on the Markdown. */
const BLOCKS: ReadonlyArray<{ page: readonly [number, number]; md: number }> = [
  { page: [18, 22], md: 50 },
  { page: [18, 60], md: 70 },
  { page: [18, 100], md: 94 },
  { page: [W / 2 + 6, 100], md: 114 },
  { page: [18, 160], md: 144 },
  { page: [18, 214], md: 172 },
];

/** The linked graph (step 5): a hub page and three it names, one not yet linked live. */
const GRAPH_HUB = { x: 520, y: 0, top: 390 } as const;
const GRAPH_NODES: ReadonlyArray<{ x: number; y: number; top: number; tag?: string; live: boolean }> = [
  { x: 660, y: 0, top: 450, tag: "Article", live: true },
  { x: 620, y: 0, top: 360, live: true },
  { x: 480, y: 0, top: 290, tag: "Organization", live: false },
];

export default function Scene() {
  const hub = pt(GRAPH_HUB.x, GRAPH_HUB.y, GRAPH_HUB.top);
  const graphPts = GRAPH_NODES.map((n) => pt(n.x, n.y, n.top)) as [
    readonly [number, number], readonly [number, number], readonly [number, number],
  ];
  const dotPath = `M${hub[0].toFixed(2)} ${hub[1]} L${graphPts[0][0].toFixed(2)} ${graphPts[0][1]} `
    + `L${hub[0].toFixed(2)} ${hub[1]} L${graphPts[1][0].toFixed(2)} ${graphPts[1][1]} `
    + `L${hub[0].toFixed(2)} ${hub[1]} L${graphPts[2][0].toFixed(2)} ${graphPts[2][1]} `
    + `L${hub[0].toFixed(2)} ${hub[1]}`;

  return (
    <svg className="how-scene" viewBox="30 40 700 510" role="img" aria-labelledby="how-scene-title" focusable="false">
      <title id="how-scene-title">
        Pages discovered across a site, one fetched twice and merged, its hidden parts
        lifted away, cut into reading order and written as Markdown, then linked into a
        graph.
      </title>
      <defs>
        <radialGradient id="how-floor-fade" cx="50%" cy="60%" r="55%">
          <stop offset="0" stopColor="#fff" />
          <stop offset="0.7" stopColor="#fff" stopOpacity="0.6" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
        <mask id="how-floor-mask">
          <rect width="760" height="560" fill="url(#how-floor-fade)" />
        </mask>
        <linearGradient id="how-shadow" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" className="sh0" />
          <stop offset="1" className="sh1" />
        </linearGradient>
        {/* Each dotted path is revealed through a mask whose stroke draws itself. */}
        <mask id="how-draw-a">
          <path className="draw" d={PATH_A} pathLength={1} transform={floor(0, 0)} />
        </mask>
        <mask id="how-draw-b">
          <path className="draw" d={PATH_B} pathLength={1} transform={floor(0, 0)} />
        </mask>
      </defs>

      {/* The floor: a ruled grid, fading at the edges. */}
      <g className="floor" mask="url(#how-floor-mask)">
        <g transform={floor(0, 0)}>
          {Array.from({ length: 21 }, (_, k) => {
            const p = -440 + k * 44;
            return (
              <g key={k}>
                <line x1={p} y1={-440} x2={p} y2={480} />
                <line x1={-440} y1={p} x2={480} y2={p} />
              </g>
            );
          })}
        </g>
      </g>

      <g className="world">
        {/* ---- step 2: two sources and their paths (real step 1: fetch twice) ---- */}
        <g className="par" data-d="0.35">
          <g className="rise s2" style={i(1)}>
            <Shadow x={-190} y={20} w={120} s={70} />
            <Sheet x={-190} y={20} top={150} w={120} h={150}>
              <Lines rows={[[14, 18, 70, 8, "ink"], [14, 36, 92, 4], [14, 46, 84, 4], [14, 56, 60, 4]]} />
              <rect x={14} y={70} width={92} height={38} className="ghost" rx={2} />
              <rect x={14} y={116} width={92} height={22} className="ghost" rx={2} />
              <Tag u={-6} v={132} text="static · 2,108 words" />
            </Sheet>
          </g>
        </g>
        <g className="par" data-d="0.5">
          <g className="rise s2" style={i(2)}>
            <Shadow x={-190} y={150} w={120} s={70} />
            <Sheet x={-190} y={150} top={150} w={120} h={150}>
              <Lines rows={[[14, 18, 70, 8, "ink"], [14, 36, 92, 4], [14, 46, 84, 4], [14, 56, 90, 4], [14, 66, 52, 4]]} />
              <Grid u={14} v={78} w={92} h={30} cols={3} rows={3} />
              <Lines rows={[[14, 118, 92, 4], [14, 128, 66, 4]]} />
              <Tag u={-6} v={132} text="rendered · 2,195 words" />
            </Sheet>
          </g>
        </g>
        <g className="rise s2" style={i(3)}>
          <g mask="url(#how-draw-a)">
            <path className="dots" d={PATH_A} pathLength={1} transform={floor(0, 0)} />
          </g>
          <g mask="url(#how-draw-b)">
            <path className="dots" d={PATH_B} pathLength={1} transform={floor(0, 0)} />
          </g>
        </g>

        {/* ---- the page, shared by fetch twice / refuse the walls / reading order ---- */}
        <g className="par" data-d="0.7">
          <g className="core" style={i(0)}>
            <Shadow x={0} y={0} w={W} s={110} />
            <Sheet x={0} y={0} top={H} w={W} h={H}>
              <Page />
              <g className="pop s2" style={i(4)}>
                {/* A quiet pulse behind the tag once it settles, so "fetched and merged"
                    keeps reading as live rather than a still frame (how.css: .glow). */}
                <circle className="glow" cx={40} cy={H - 10} r={14} style={i(0)} />
                <Tag u={-6} v={H - 18} text="union · 2,198 words" tone="good" />
              </g>
              {/* step 4: the XY-cut lines */}
              <path className="cut" d={`M12 72 H${W - 12}`} pathLength={1} />
              <path className="cut" d={`M${W / 2} 80 V132`} pathLength={1} style={i(1)} />
              <path className="cut" d={`M12 140 H${W - 12}`} pathLength={1} style={i(2)} />
              <path className="cut" d={`M12 198 H${W - 12}`} pathLength={1} style={i(3)} />
            </Sheet>
          </g>
          {/* step 4: the blocks numbered in reading order, in screen space so they stay round */}
          {BLOCKS.map(({ page }, n) => (
            <g key={n} transform={at(onPage(...page))}>
              <g className="num pop s4" style={i(n + 1)}>
                <circle r={8} />
                <text y={3.2}>{n + 1}</text>
              </g>
            </g>
          ))}
        </g>

        {/* ---- step 3: the page exploded (real step 2: refuse the walls, drop the hidden) ---- */}
        <g className="par" data-d="1">
          <g className="rise s3" style={i(1)}>
            <Sheet x={16} y={56} top={218} w={104} h={26} thin>
              <rect x={10} y={8} width={64} height={9} rx={1.5} className="ink" />
              <Tag u={-8} v={16} text="Heading" />
            </Sheet>
          </g>
          <g className="rise s3" style={i(2)}>
            <Sheet x={16} y={84} top={176} w={104} h={40} thin>
              <Lines rows={[[10, 9, 84, 4], [10, 18, 76, 4], [10, 27, 60, 4]]} />
              <Tag u={-8} v={30} text="Paragraph" />
            </Sheet>
          </g>
          <g className="rise s3" style={i(3)}>
            <Sheet x={16} y={112} top={122} w={104} h={50} thin>
              <Grid u={10} v={8} w={84} h={34} cols={3} rows={3} />
              <Tag u={-8} v={40} text="Table" />
            </Sheet>
          </g>
          <g className="rise s3" style={i(4)}>
            <Sheet x={16} y={140} top={60} w={104} h={34} thin>
              <rect x={10} y={8} width={84} height={18} rx={2} className="sunk" />
              <Lines rows={[[16, 13, 40, 3, "code"], [16, 19, 56, 3, "code"]]} />
              <Tag u={-8} v={24} text="Code" />
            </Sheet>
          </g>
        </g>
        <g className="par" data-d="1.3">
          <g className="hid s3" style={i(0)}>
            <Sheet x={-90} y={24} top={156} w={64} h={44} tone="bad" thin>
              <Lines rows={[[8, 8, 48, 3, "bad"], [8, 15, 44, 3, "bad"], [8, 22, 48, 3, "bad"], [8, 29, 36, 3, "bad"]]} />
              <Tag u={-6} v={36} text="off-screen links" tone="bad" />
            </Sheet>
          </g>
          <g className="hid s3" style={i(1)}>
            <Sheet x={96} y={24} top={168} w={96} h={62} tone="bad" thin>
              <rect x={10} y={10} width={50} height={7} rx={1.5} className="bad" />
              <rect x={10} y={24} width={76} height={9} rx={2} className="line-bad" />
              <rect x={10} y={37} width={76} height={9} rx={2} className="line-bad" />
              <rect x={30} y={50} width={36} height={8} rx={2} className="bad" />
              <Tag u={-6} v={52} text="login modal" tone="bad" />
            </Sheet>
          </g>
          <g className="hid s3" style={i(2)}>
            <Sheet x={110} y={24} top={92} w={84} h={30} tone="bad" thin>
              <rect x={8} y={8} width={68} height={14} rx={2} className="line-bad" />
              <Tag u={-6} v={22} text="display:none" tone="bad" />
            </Sheet>
          </g>
          <g className="hid s3" style={i(3)}>
            <Sheet x={40} y={24} top={44} w={140} h={24} tone="bad" thin>
              <Lines rows={[[8, 7, 70, 3, "bad"], [8, 14, 54, 3, "bad"]]} />
              <rect x={96} y={7} width={26} height={10} rx={2} className="bad" />
              <Tag u={-6} v={18} text="cookie banner" tone="bad" />
            </Sheet>
          </g>
          <g className="pop s3" style={i(5)}>
            <g transform={wall(20, 30, 278)}>
              <Tag u={0} v={0} text="refused · redirected to a login page" tone="bad" />
            </g>
          </g>
        </g>

        {/* ---- step 4: the Markdown and the report (real step 3: reading order, then Markdown) ---- */}
        <g className="par" data-d="0.55">
          <g className="rise s4" style={i(1)}>
            <Shadow x={MD.x} y={MD.y} w={MD.w} s={80} />
            <Sheet x={MD.x} y={MD.y} top={MD.top} w={MD.w} h={MD.h}>
              <text x={10} y={13} className="faint">---</text>
              <text x={10} y={24}>reading_order: geometric_xy_cut</text>
              <text x={10} y={35} className="faint">---</text>
              <text x={10} y={54} className="faint">#</text>
              <rect x={22} y={47} width={72} height={7} rx={2} className="ink" />
              <Lines rows={[[10, 66, 128, 4], [10, 74, 110, 4], [10, 90, 96, 4], [10, 98, 80, 4], [10, 110, 100, 4], [10, 118, 70, 4]]} />
              <text x={10} y={142} className="faint">|</text>
              <Grid u={22} v={132} w={112} h={24} cols={4} rows={3} />
              <text x={10} y={172} className="faint">```</text>
              <rect x={30} y={164} width={104} height={16} rx={2} className="sunk" />
              <Lines rows={[[36, 169, 40, 3, "code"], [36, 175, 60, 3, "code"]]} />
              {/* A cursor blinking at the end of the last line: "still writing" (how.css: .cursor). */}
              <rect className="cursor" x={98} y={174} width={2} height={5} />
            </Sheet>
          </g>
          {BLOCKS.map(({ md }, n) => (
            <g key={n} transform={at(onMd(md))}>
              <g className="num pop s4" style={i(n + 4)}>
                <circle r={7} />
                <text y={3}>{n + 1}</text>
              </g>
            </g>
          ))}
        </g>
        <g className="par" data-d="0.9">
          <g className="rise s4" style={i(6)}>
            <Shadow x={230} y={20} w={140} s={34} />
            <Sheet x={230} y={20} top={104} w={140} h={72}>
              <rect x={0} y={0} width={140} height={16} className="head" />
              <text x={8} y={11} className="strong">Site Truth Report</text>
              <Lines rows={[[8, 28, 36, 4], [8, 42, 36, 4], [8, 56, 36, 4]]} />
              <text x={52} y={32}>walls · 1, named</text>
              <text x={52} y={46}>hidden · 2,100 words</text>
              <text x={52} y={60} className="good">order · measured</text>
            </Sheet>
          </g>
        </g>

        {/* ---- step 5: build the graph -- a hub page and the entities it names, linked ---- */}
        <g className="s5">
          <line x1={hub[0]} y1={hub[1]} x2={graphPts[0][0]} y2={graphPts[0][1]} className="step-edge-live" />
          <line x1={hub[0]} y1={hub[1]} x2={graphPts[1][0]} y2={graphPts[1][1]} className="step-edge-live" />
          <line x1={hub[0]} y1={hub[1]} x2={graphPts[2][0]} y2={graphPts[2][1]} className="step-edge" />
        </g>
        <g className="rise s5" style={i(1)}>
          <Sheet x={GRAPH_HUB.x} y={GRAPH_HUB.y} top={GRAPH_HUB.top} w={44} h={40}>
            <rect x={6} y={7} width={28} height={5} rx={1.5} className="ink" />
            <rect x={6} y={17} width={32} height={3} rx={1.5} className="line" />
            <rect x={6} y={24} width={22} height={3} rx={1.5} className="line" />
          </Sheet>
        </g>
        {GRAPH_NODES.map((n, k) => (
          <g className="rise s5" style={i(k + 2)} key={`graph-${k}`}>
            <Sheet x={n.x} y={n.y} top={n.top} w={44} h={40}>
              <rect x={6} y={7} width={n.tag ? 26 : 30} height={5} rx={1.5} className="ink" />
              <rect x={6} y={17} width={n.tag ? 30 : 24} height={3} rx={1.5} className="line" />
            </Sheet>
            {n.tag ? (
              <g transform={wall(n.x - (n.tag.length * 5.7 + 12 - 44) / 2, n.y, n.top + 18)}>
                <Tag u={0} v={0} text={n.tag} tone="good" />
              </g>
            ) : null}
          </g>
        ))}
        <g className="s5">
          <circle className="graph-dot" r={3.5}>
            <animateMotion dur="5s" repeatCount="indefinite" path={dotPath} />
          </circle>
        </g>
      </g>
    </svg>
  );
}

const PATH_A = "M-64 36 Q0 62 44 12";
const PATH_B = "M-64 162 Q40 192 124 14";

const at = ([x, y]: readonly [number, number]) => `translate(${x.toFixed(1)} ${y.toFixed(1)})`;

/* ---- pieces, in the local coordinates of a `wall` or `floor` group -------------------- */

function Sheet({
  x, y, top, w, h, tone, thin = false, children,
}: {
  x: number; y: number; top: number; w: number; h: number;
  tone?: "bad";
  thin?: boolean;
  children?: ReactNode;
}) {
  const t = thin ? 2.5 : 4;
  return (
    <g transform={wall(x, y, top)} className={tone === "bad" ? "sheet sheet-bad" : "sheet"}>
      <polygon className="edge" points={poly([t, -t], [w + t, -t], [w + t, h - t], [w, h], [w, 0], [0, 0])} />
      <rect className="face" width={w} height={h} />
      {children}
    </g>
  );
}

/** A sheet's shadow on the floor, from a light behind and above. */
function Shadow({ x, y, w, s }: { x: number; y: number; w: number; s: number }) {
  return (
    <g transform={floor(x, y)}>
      <rect className="shadow" x={-2} y={0} width={w + 4} height={s} />
    </g>
  );
}

type Row = readonly [u: number, v: number, w: number, h: number, tone?: "ink" | "code" | "bad"];

function Lines({ rows }: { rows: readonly Row[] }) {
  return (
    <>
      {rows.map(([u, v, w, h, tone], k) => (
        <rect key={k} x={u} y={v} width={w} height={h} rx={h / 2} className={tone ?? "line"} />
      ))}
    </>
  );
}

function Grid({ u, v, w, h, cols, rows }: { u: number; v: number; w: number; h: number; cols: number; rows: number }) {
  const d: string[] = [];
  for (let c = 1; c < cols; c++) d.push(`M${u + (w / cols) * c} ${v} v${h}`);
  for (let r = 1; r < rows; r++) d.push(`M${u} ${v + (h / rows) * r} h${w}`);
  return (
    <g className="grid">
      <rect x={u} y={v} width={w} height={h / rows} className="head" />
      <rect x={u} y={v} width={w} height={h} rx={2} />
      <path d={d.join(" ")} />
    </g>
  );
}

function Tag({ u, v, text, tone }: { u: number; v: number; text: string; tone?: "bad" | "good" }) {
  const w = text.length * 5.7 + 12;
  return (
    <g className={`tag${tone ? ` tag-${tone}` : ""}`} transform={`translate(${u} ${v})`}>
      <rect width={w} height={16} rx={3} />
      <text x={6} y={11}>{text}</text>
    </g>
  );
}

/** The page's content: heading, a paragraph, two columns, a table, a code block. */
function Page() {
  return (
    <>
      <Lines rows={[[16, 16, 112, 10, "ink"], [16, 42, 168, 4], [16, 52, 152, 4], [16, 62, 160, 4]]} />
      <Lines
        rows={[
          [16, 84, 82, 4], [16, 94, 74, 4], [16, 104, 80, 4], [16, 114, 60, 4], [16, 124, 76, 4],
          [112, 84, 72, 4], [112, 94, 66, 4], [112, 104, 72, 4], [112, 114, 50, 4], [112, 124, 66, 4],
        ]}
      />
      <Grid u={16} v={148} w={168} h={42} cols={4} rows={3} />
      <rect x={16} y={204} width={168} height={22} rx={3} className="sunk" />
      <Lines rows={[[24, 210, 56, 3, "code"], [24, 217, 90, 3, "code"]]} />
    </>
  );
}
