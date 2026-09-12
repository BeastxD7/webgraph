import { SCRAPE_PLANE } from "@/lib/benchmarks";

/**
 * scrape-evals on two axes: how much an engine could fetch, against how well it extracted it.
 *
 * Drawn rather than ranked because the two axes are independent and the ranking hides what
 * they say together. Every dimension carries meaning: position is the measurement, fill is
 * whether the engine pays for anti-bot infrastructure, and only that. No size encoding, no
 * colour ramp -- there is no third variable, so adding one would be decoration.
 *
 * The viewBox leaves room for the outermost labels, and both axes start well below the data
 * rather than at zero: every engine here scores above 0.30, and an axis from zero would
 * compress the entire field into the top third and say nothing.
 */
const X0 = 0.35;
const X1 = 0.85;
const Y0 = 0.3;
const Y1 = 0.72;

const PAD = { left: 40, right: 16, top: 14, bottom: 36 };
const W = 520;
const H = 310;
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

const x = (v: number) => PAD.left + ((v - X0) / (X1 - X0)) * PLOT_W;
const y = (v: number) => PAD.top + (1 - (v - Y0) / (Y1 - Y0)) * PLOT_H;

const X_TICKS = [0.4, 0.5, 0.6, 0.7, 0.8];
const Y_TICKS = [0.3, 0.4, 0.5, 0.6, 0.7];

/**
 * Label placement for the crowded middle.
 *
 * Seven engines sit inside a band six points wide and four points tall, so default placement
 * overlaps four of them into unreadability. Each entry says which side of its marker the
 * label sits on and how far, chosen by looking at the plot rather than by a rule. Anything
 * not listed takes the default: to the right, vertically centred.
 */
type Label = { readonly dx: number; readonly dy: number; readonly anchor: "start" | "end" | "middle" };

const LABELS: Record<string, Label> = {
  Crawl4AI: { dx: -9, dy: -8, anchor: "end" },
  Zyte: { dx: 0, dy: -11, anchor: "middle" },
  ScraperAPI: { dx: 9, dy: -6, anchor: "start" },
  ScrapingBee: { dx: -9, dy: 4, anchor: "end" },
  Apify: { dx: 0, dy: 15, anchor: "middle" },
  Scrapy: { dx: -9, dy: 4, anchor: "end" },
  Puppeteer: { dx: -9, dy: 4, anchor: "end" },
  Selenium: { dx: 0, dy: 15, anchor: "middle" },
  webgraph: { dx: 16, dy: 4, anchor: "start" },
};

const DEFAULT_LABEL: Label = { dx: 9, dy: 3.5, anchor: "start" };

export default function ScatterPlane() {
  return (
    <figure className="min-w-0">
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="h-auto w-full min-w-[400px]"
          role="img"
          aria-label="Coverage against extraction quality for fourteen scraping engines on 1,000 live URLs."
        >
          {Y_TICKS.map((tick) => (
            <g key={`y${tick}`}>
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
                {tick.toFixed(1)}
              </text>
            </g>
          ))}

          {X_TICKS.map((tick) => (
            <text
              key={`x${tick}`}
              x={x(tick)}
              y={H - PAD.bottom + 14}
              textAnchor="middle"
              className="fill-ink-faint font-mono text-[8.5px]"
            >
              {Math.round(tick * 100)}%
            </text>
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
            y={H - 4}
            textAnchor="middle"
            className="fill-ink-soft text-[9.5px] font-semibold"
          >
            Pages fetched successfully
          </text>
          <text
            x={-(PAD.top + PLOT_H / 2)}
            y={11}
            transform="rotate(-90)"
            textAnchor="middle"
            className="fill-ink-soft text-[9.5px] font-semibold"
          >
            Extraction quality (F1)
          </text>

          {SCRAPE_PLANE.map((point) => {
            const label = LABELS[point.name] ?? DEFAULT_LABEL;
            const cx = x(point.coverage);
            const cy = y(point.quality);
            return (
              <g key={point.name}>
                <circle
                  cx={cx}
                  cy={cy}
                  r={point.self ? 5 : 3.5}
                  className={
                    point.self
                      ? "fill-leaf-600"
                      : point.proxy
                        ? "fill-clay/70"
                        : "fill-ink-faint/55"
                  }
                />
                {point.self ? (
                  <circle
                    cx={cx}
                    cy={cy}
                    r={9}
                    fill="none"
                    className="stroke-leaf-600"
                    strokeWidth="1.4"
                  />
                ) : null}
                <text
                  x={cx + label.dx}
                  y={cy + label.dy}
                  textAnchor={label.anchor}
                  className={
                    point.self
                      ? "fill-ink text-[9px] font-bold"
                      : "fill-ink-soft text-[8.5px]"
                  }
                >
                  {point.name}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11.5px] text-ink-faint">
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-full bg-leaf-600" /> this engine
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-full bg-clay/70" /> commercial proxy or anti-bot
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-full bg-ink-faint/55" /> own address, no proxy
        </span>
      </div>

      <figcaption className="mt-4 text-[12.5px] leading-relaxed text-ink-faint">
        The field separates horizontally, not vertically. Engines that pay for anti-bot
        infrastructure sit further right because they fetch more pages, and barely higher,
        because extraction quality is not what they bought. Among the engines fetching from
        their own address this one is furthest right and second highest. Axes are clipped to
        the data; neither starts at zero.
      </figcaption>
    </figure>
  );
}
