import { CAM, PLINTH, project, seedPages } from "./geometry";

/**
 * The hero before JavaScript, and its first frame: the sky, the ground, the plinth and the
 * nearest few hundred pages of the field, as server-rendered SVG in a 1440×900 box that
 * `slice`s to the frame. Every colour is a token, so it follows the theme like the canvas.
 * The live field hides it once it draws (`[data-field] .hero-still`).
 */
const W = 1440;
const H = 900;
const PAGES = seedPages(260, 7)
  .map((p) => ({ p, base: project(p.x, 0, p.z, W, H) }))
  .filter((e): e is { p: (typeof e)["p"]; base: NonNullable<(typeof e)["base"]> } => e.base !== null)
  .sort((a, b) => b.p.z - a.p.z);

const HORIZON = project(0, 0, 1e6, W, H)?.y ?? H * 0.55;
const PL = {
  a: project(PLINTH.x - PLINTH.w / 2, PLINTH.h, PLINTH.z + PLINTH.d / 2, W, H),
  b: project(PLINTH.x + PLINTH.w / 2, PLINTH.h, PLINTH.z + PLINTH.d / 2, W, H),
  c: project(PLINTH.x + PLINTH.w / 2, PLINTH.h, PLINTH.z - PLINTH.d / 2, W, H),
  d: project(PLINTH.x - PLINTH.w / 2, PLINTH.h, PLINTH.z - PLINTH.d / 2, W, H),
  e: project(PLINTH.x + PLINTH.w / 2, 0, PLINTH.z - PLINTH.d / 2, W, H),
  f: project(PLINTH.x - PLINTH.w / 2, 0, PLINTH.z - PLINTH.d / 2, W, H),
};

const FILL = ["var(--paper)", "var(--paper-junk)", "var(--paper-hidden)", "var(--paper)"] as const;

export default function HeroStill() {
  const fog = (z: number) => Math.min(0.92, Math.max(0, (z - 6) / (CAM.far * 0.34)));
  return (
    <svg
      aria-hidden
      className="hero-still absolute inset-0 size-full"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="xMidYMid slice"
    >
      <defs>
        <linearGradient id="hs-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--sky-top)" />
          <stop offset="0.55" stopColor="var(--sky-mid)" />
          <stop offset="1" stopColor="var(--sky-horizon)" />
        </linearGradient>
        <linearGradient id="hs-ground" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--haze)" />
          <stop offset="0.18" stopColor="var(--field-far)" />
          <stop offset="1" stopColor="var(--field-near)" />
        </linearGradient>
        <radialGradient id="hs-sun" cx="0.68" cy="0.98" r="0.5">
          <stop offset="0" stopColor="var(--sun)" stopOpacity="0.9" />
          <stop offset="1" stopColor="var(--sun)" stopOpacity="0" />
        </radialGradient>
        <filter id="hs-blur" x="-20%" y="-50%" width="140%" height="200%">
          <feGaussianBlur stdDeviation="18" />
        </filter>
      </defs>
      <rect width={W} height={HORIZON} fill="url(#hs-sky)" />
      <rect width={W} height={HORIZON} fill="url(#hs-sun)" />
      <g fill="var(--cloud)" opacity="0.55" filter="url(#hs-blur)">
        <ellipse cx={300} cy={150} rx={220} ry={26} />
        <ellipse cx={980} cy={110} rx={300} ry={22} />
        <ellipse cx={1240} cy={250} rx={190} ry={18} />
        <ellipse cx={620} cy={300} rx={260} ry={16} />
      </g>
      <rect y={HORIZON} width={W} height={H - HORIZON} fill="url(#hs-ground)" />
      {PL.a && PL.b && PL.c && PL.d && PL.e && PL.f && (
        <g>
          <ellipse cx={(PL.e.x + PL.f.x) / 2} cy={PL.e.y + 6} rx={(PL.e.x - PL.f.x) * 0.62} ry={22} fill="var(--ink)" opacity="0.16" filter="url(#hs-blur)" />
          <polygon points={`${PL.d.x},${PL.d.y} ${PL.c.x},${PL.c.y} ${PL.e.x},${PL.e.y} ${PL.f.x},${PL.f.y}`} fill="var(--plinth-side)" />
          <polygon points={`${PL.a.x},${PL.a.y} ${PL.b.x},${PL.b.y} ${PL.c.x},${PL.c.y} ${PL.d.x},${PL.d.y}`} fill="var(--plinth)" />
        </g>
      )}
      {PAGES.map(({ p, base }, i) => {
        const h = p.h * base.s;
        const w = p.w * base.s;
        const x = base.x - w / 2 + p.lean * h * 0.35;
        const y = base.y - h;
        return (
          <g key={i} transform={`rotate(${(p.lean * 180) / Math.PI / 3} ${base.x} ${base.y})`}>
            <rect x={x} y={y} width={w} height={h} rx={Math.min(1.5, w * 0.06)} fill={FILL[p.kind]} />
            {h > 26 && p.kind !== 2 && (
              <g fill={p.kind === 1 ? "var(--paper)" : "var(--paper-ink)"} opacity={p.kind === 1 ? 0.45 : 0.32}>
                {p.lines.map((len, j) => (
                  <rect key={j} x={x + w * 0.16} y={y + h * (0.2 + j * 0.16)} width={w * 0.68 * len} height={Math.max(0.8, h * 0.035)} />
                ))}
              </g>
            )}
            {fog(p.z) > 0.02 && <rect x={x} y={y} width={w} height={h} fill="var(--haze)" opacity={fog(p.z)} />}
          </g>
        );
      })}
    </svg>
  );
}
