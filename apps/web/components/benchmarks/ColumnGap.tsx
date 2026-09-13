import { COLUMNS } from "@/lib/benchmarks";

/**
 * WebMainBench's five columns, this engine against the leader, as paired vertical bars.
 *
 * This is the chart that carries the argument. An overall score averages these five and hides
 * that three of them are close and two are chasms, so the pairing per column is the thing to
 * read first. Grouped rather than stacked: the two bars are alternatives, not parts of a whole.
 */
const PAD = { left: 34, right: 8, top: 16, bottom: 42 };
const BAR_W = 16;
const PAIR_GAP = 3;
const GROUP_GAP = 24;
const PLOT_H = 140;
const TICKS = [0, 0.25, 0.5, 0.75, 1];

export default function ColumnGap() {
  const groupW = BAR_W * 2 + PAIR_GAP;
  const plotW = COLUMNS.length * groupW + (COLUMNS.length - 1) * GROUP_GAP;
  const width = PAD.left + plotW + PAD.right;
  const height = PAD.top + PLOT_H + PAD.bottom;

  const y = (v: number) => PAD.top + (1 - v) * PLOT_H;
  const groupX = (i: number) => PAD.left + i * (groupW + GROUP_GAP);

  return (
    <figure className="min-w-0">
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-auto w-full"
          style={{ minWidth: `${Math.min(width, 380)}px` }}
          role="img"
          aria-label={`Per-column comparison: ${COLUMNS.map(
            (c) => `${c.label}, this engine ${c.us.toFixed(3)} against ${c.best.toFixed(3)}`,
          ).join("; ")}.`}
        >
          {TICKS.map((tick) => (
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

          {COLUMNS.map((column, i) => {
            const x0 = groupX(i);
            const bars = [
              { value: column.us, self: true, x: x0 },
              { value: column.best, self: false, x: x0 + BAR_W + PAIR_GAP },
            ];
            return (
              <g key={column.key}>
                {bars.map((bar) => (
                  <g key={bar.self ? "us" : "them"}>
                    <rect
                      x={bar.x}
                      y={y(bar.value)}
                      width={BAR_W}
                      height={Math.max(1, y(0) - y(bar.value))}
                      rx="2"
                      className={bar.self ? "fill-leaf-600" : "fill-clay/55"}
                    />
                    <text
                      x={bar.x + BAR_W / 2}
                      y={y(bar.value) - 4.5}
                      textAnchor="middle"
                      className={
                        bar.self
                          ? "fill-leaf-700 font-mono text-[8px] font-bold"
                          : "fill-ink-faint font-mono text-[8px]"
                      }
                    >
                      {bar.value.toFixed(2)}
                    </text>
                  </g>
                ))}
                <text
                  x={x0 + groupW / 2}
                  y={y(0) + 13}
                  textAnchor="middle"
                  className="fill-ink text-[9px] font-semibold"
                >
                  {column.label}
                </text>
                <text
                  x={x0 + groupW / 2}
                  y={y(0) + 23}
                  textAnchor="middle"
                  className="fill-ink-faint font-mono text-[8px]"
                >
                  {column.pages}p
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11.5px] text-ink-faint">
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[2px] bg-leaf-600" /> this engine
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[2px] bg-clay/55" /> MinerU-HTML, the leader
        </span>
      </div>

      <figcaption className="mt-4 text-[12.5px] leading-relaxed text-ink-faint">
        Equations started the day at 0.307 and half the gap was currency: an unescaped dollar
        amount reads as a maths delimiter, so two prices in one paragraph scored as a formula
        wrapping the prose between them. The rest was MathML, which the engine deleted before
        extraction began. Tables started at 0.349; a merged-cell table cannot be written in
        Markdown pipe syntax without losing the merges, so those now keep their own markup,
        and tables that were really navigation widgets are no longer emitted as tables at all.
        This round moved prose 0.767 to 0.774 and equations 0.517 to 0.605, and cost tables
        0.425 to 0.404 &mdash; not yet diagnosed, and recorded rather than hidden.
      </figcaption>
    </figure>
  );
}
