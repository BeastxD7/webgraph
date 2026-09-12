import type { Board } from "@/lib/benchmarks";

/**
 * One board as a vertical column chart with a scored axis.
 *
 * Columns are in the board's own ranking order and are never reordered to flatter this
 * engine: where it places eighth, it is drawn eighth. Only one thing is encoded by colour --
 * whether the column is ours -- because there is no second variable to encode.
 *
 * The axis starts at zero. A chart of extraction scores that starts at 0.6 turns a
 * three-point difference into a visual landslide, which is the most common way a benchmark
 * chart misleads, and these boards are close enough at the top for it to matter.
 *
 * Labels are rotated rather than truncated: these are system names, and half of a system name
 * identifies nothing.
 */
const PAD = { left: 34, right: 8, top: 16, bottom: 56 };
const COL_W = 20;
const GAP = 9;
const PLOT_H = 132;

const TICKS = [0, 0.25, 0.5, 0.75, 1];

export default function RankChart({ board }: { board: Board }) {
  const count = board.entries.length;
  const plotW = count * COL_W + (count - 1) * GAP;
  const width = PAD.left + plotW + PAD.right;
  const height = PAD.top + PLOT_H + PAD.bottom;

  const y = (v: number) => PAD.top + (1 - v / board.max) * PLOT_H;
  const columnX = (i: number) => PAD.left + i * (COL_W + GAP);

  return (
    <figure className="min-w-0">
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-auto w-full"
          style={{ minWidth: `${Math.min(width, 420)}px` }}
          role="img"
          aria-label={`${board.name}: ${board.entries
            .map((e) => `${e.name} ${e.score.toFixed(3)}`)
            .join(", ")}.`}
        >
          {TICKS.filter((t) => t <= board.max).map((tick) => (
            <g key={tick}>
              <line
                x1={PAD.left}
                x2={width - PAD.right}
                y1={y(tick)}
                y2={y(tick)}
                stroke="currentColor"
                className={tick === 0 ? "text-line-strong" : "text-line"}
                strokeWidth="1"
              />
              <text
                x={PAD.left - 8}
                y={y(tick) + 3.5}
                textAnchor="end"
                className="fill-ink-faint font-mono text-[8.5px]"
              >
                {tick.toFixed(2)}
              </text>
            </g>
          ))}

          {board.entries.map((entry, i) => {
            const top = y(entry.score);
            const cx = columnX(i) + COL_W / 2;
            return (
              <g key={entry.name}>
                <rect
                  x={columnX(i)}
                  y={top}
                  width={COL_W}
                  height={Math.max(1, y(0) - top)}
                  rx="2"
                  className={entry.self ? "fill-leaf-600" : "fill-ink-faint/40"}
                />
                <text
                  x={cx}
                  y={top - 4.5}
                  textAnchor="middle"
                  className={
                    entry.self
                      ? "fill-leaf-700 font-mono text-[8.5px] font-bold"
                      : "fill-ink-faint font-mono text-[8px]"
                  }
                >
                  {entry.score.toFixed(3)}
                </text>
                <text
                  x={cx}
                  y={y(0) + 8}
                  transform={`rotate(-42 ${cx} ${y(0) + 8})`}
                  textAnchor="end"
                  className={
                    entry.self
                      ? "fill-ink text-[8.5px] font-bold"
                      : "fill-ink-soft text-[8px]"
                  }
                >
                  {entry.name}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {board.entries.some((e) => e.note) ? (
        <figcaption className="mt-3 flex flex-col gap-1 text-[12px] leading-snug text-ink-faint">
          {board.entries
            .filter((e) => e.note)
            .map((e) => (
              <span key={e.name}>
                <span className={e.self ? "font-semibold text-ink-soft" : ""}>{e.name}</span>
                {" — "}
                {e.note}
              </span>
            ))}
        </figcaption>
      ) : null}
    </figure>
  );
}
