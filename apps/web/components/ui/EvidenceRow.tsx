import type { CSSProperties, ReactNode } from "react";

/**
 * One fact, its label and where it came from, on a rule (DESIGN.md §6). The value is set in
 * mono when it is a message or an address the engine emitted verbatim.
 */
export default function EvidenceRow({
  label,
  value,
  source,
  mono = false,
  index,
}: {
  label: string;
  value: ReactNode;
  source?: ReactNode;
  mono?: boolean;
  /** When given, the row slides in on scroll, `index` × 70ms after the one before. */
  index?: number;
}) {
  return (
    <div
      className="grid gap-x-4 gap-y-1 border-b border-rule py-3 sm:grid-cols-[8.5rem_1fr]"
      data-reveal={index === undefined ? undefined : "slide"}
      style={index === undefined ? undefined : ({ "--i": index } as CSSProperties)}
    >
      <dt className="text-small font-semibold text-ink">{label}</dt>
      <dd className="min-w-0">
        <p className={mono ? "break-words font-mono text-code text-ink" : "text-small text-ink"}>
          {value}
        </p>
        {source && <p className="mt-0.5 text-small text-muted">{source}</p>}
      </dd>
    </div>
  );
}
