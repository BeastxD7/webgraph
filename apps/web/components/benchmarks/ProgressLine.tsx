import { PROGRESSION } from "@/lib/benchmarks";

/**
 * WCXB across one session, plotted against the fix that produced each point.
 *
 * A line rather than bars because this is a sequence measured cumulatively: every point was
 * scored on top of the one before it, so the slope between two points is the value of one
 * fix. The fourth step is four times the height of any other, which is the whole finding and
 * is visible immediately in a line and not at all in a ranked list.
 */
const SCORES = PROGRESSION.map((s) => s.score);
const Y0 = Math.floor((Math.min(...SCORES) - 0.01) * 100) / 100;
const Y1 = Math.ceil((Math.max(...SCORES) + 0.01) * 100) / 100;
const PAD = { left: 36, right: 14, top: 16, bottom: 40 };
const W = 480;
const H = 210;
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

const y = (v: number) => PAD.top + (1 - (v - Y0) / (Y1 - Y0)) * PLOT_H;
const x = (i: number) => PAD.left + (i / (PROGRESSION.length - 1)) * PLOT_W;

const TICKS = Array.from({ length: 5 }, (_, i) => Math.round((Y0 + ((Y1 - Y0) * i) / 4) * 1000) / 1000);

export default function ProgressLine() {
  const path = PROGRESSION.map((s, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(s.score)}`).join(" ");
  const area = `${path} L${x(PROGRESSION.length - 1)},${H - PAD.bottom} L${PAD.left},${H - PAD.bottom} Z`;

  return (
    <figure className="min-w-0">
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="h-auto w-full min-w-[360px]"
          role="img"
          aria-label={`WCXB F1 rising from ${(SCORES[0] ?? 0).toFixed(3)} to ${(SCORES[SCORES.length - 1] ?? 0).toFixed(3)} across ${PROGRESSION.length - 1} steps.`}
        >
          {TICKS.map((tick) => (
            <g key={tick}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y(tick)}
                y2={y(tick)}
                stroke="currentColor"
                className="text-line"
                strokeWidth="1"
              />
              <text
                x={PAD.left - 9}
                y={y(tick) + 4}
                textAnchor="end"
                className="fill-ink-faint font-mono text-[8.5px]"
              >
                {tick.toFixed(3)}
              </text>
            </g>
          ))}

          <path d={area} className="fill-leaf-100/55" />
          <path
            d={path}
            fill="none"
            className="stroke-leaf-600"
            strokeWidth="2"
            strokeLinejoin="round"
          />

          {PROGRESSION.map((step, i) => (
            <g key={step.label}>
              <circle cx={x(i)} cy={y(step.score)} r="3.5" className="fill-leaf-700" />
              <text
                x={x(i)}
                y={y(step.score) - 8}
                textAnchor={i === 0 ? "start" : i === PROGRESSION.length - 1 ? "end" : "middle"}
                className="fill-ink font-mono text-[9px] font-bold"
              >
                {step.score.toFixed(3)}
              </text>
              <text
                x={x(i)}
                y={H - PAD.bottom + 13}
                textAnchor={i === 0 ? "start" : i === PROGRESSION.length - 1 ? "end" : "middle"}
                className="fill-ink-faint font-mono text-[8px]"
              >
                {String(i + 1).padStart(2, "0")}
              </text>
            </g>
          ))}

          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={H - PAD.bottom}
            y2={H - PAD.bottom}
            stroke="currentColor"
            className="text-line-strong"
            strokeWidth="1"
          />
          <text
            x={PAD.left + PLOT_W / 2}
            y={H - 5}
            textAnchor="middle"
            className="fill-ink-soft text-[9.5px] font-semibold"
          >
            Extraction fixes, in the order they were measured
          </text>
        </svg>
      </div>

      <ol className="mt-4 flex flex-col gap-1.5 text-[12px] leading-snug text-ink-faint">
        {PROGRESSION.map((step, i) => (
          <li key={step.label}>
            <span className="font-mono">{String(i + 1).padStart(2, "0")}</span>{" "}
            <span className="font-semibold text-ink-soft">{step.label}</span> — {step.why}
          </li>
        ))}
      </ol>

      <figcaption className="mt-3 text-[12px] leading-relaxed text-ink-faint">
        Axis runs {Y0.toFixed(2)}–{Y1.toFixed(2)}; the production path, routed by page type,
        on the dev split. Every step is a bug found by a page-level diagnostic and measured
        before it shipped, never a threshold tuned until the number moved.
      </figcaption>
    </figure>
  );
}
