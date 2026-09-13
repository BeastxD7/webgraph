import { TYPE_ROWS, TYPE_SYSTEMS } from "@/lib/benchmarks";

/**
 * WCXB by page type: this engine beside the published systems, one row per type.
 *
 * The overall WCXB number is 53% articles, so it is mostly a score on the easy case. The
 * corpus was built to show the other six, and this is where the ranking actually moves: the
 * systems are within a few points of each other on articles and twenty apart on collections.
 *
 * The best cell in each row is picked out, whoever holds it. Ours is never sorted to the
 * front; the columns keep the order the corpus README lists them in.
 */
export default function TypeTable() {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-line-strong text-left font-mono text-[10.5px] uppercase tracking-[0.06em] text-ink-faint">
            <th className="py-2 pr-3 font-medium">Page type</th>
            <th className="py-2 pr-3 text-right font-medium">n</th>
            {TYPE_SYSTEMS.map((system) => (
              <th
                key={system.key}
                className={`py-2 pr-3 text-right font-medium ${system.self ? "text-leaf-700" : ""}`}
              >
                {system.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {TYPE_ROWS.map((row) => {
            const best = Math.max(...TYPE_SYSTEMS.map((s) => row.scores[s.key] ?? 0));
            return (
              <tr key={row.type} className="border-b border-line">
                <td className="py-2 pr-3 capitalize">{row.type}</td>
                <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink-faint">{row.n}</td>
                {TYPE_SYSTEMS.map((system) => {
                  const score = row.scores[system.key];
                  const isBest = score !== undefined && score === best;
                  return (
                    <td
                      key={system.key}
                      className={`py-2 pr-3 text-right font-mono tabular-nums ${
                        system.self ? "text-ink" : "text-ink-soft"
                      } ${isBest ? "font-bold" : ""}`}
                    >
                      {score === undefined ? "—" : score.toFixed(3)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
