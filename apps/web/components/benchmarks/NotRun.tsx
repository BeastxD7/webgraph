import { NOT_RUN } from "@/lib/benchmarks";

/**
 * Benchmarks that were looked at and could not be run here, with the reason.
 *
 * A benchmarks page that lists only the boards it scores well on is an advertisement. These
 * are the ones a reader would expect to see and will not, and the reason is stated so they can
 * judge it -- and go run them if they have what this session did not.
 */
export default function NotRun() {
  return (
    <ul className="flex flex-col gap-4">
      {NOT_RUN.map((item) => (
        <li key={item.name} className="rounded-md border border-line px-4 py-3">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h3 className="font-display text-[1.15rem] leading-tight">{item.name}</h3>
            <span className="font-mono text-[11px] text-ink-faint">{item.what}</span>
          </div>
          <p className="mt-1.5 text-small leading-relaxed text-ink-soft">{item.why}</p>
        </li>
      ))}
    </ul>
  );
}
