/**
 * A number with what it was measured on (DESIGN.md §1.4, §6). No box: the tiles are separated
 * by rules. A loss is set exactly like a win.
 */
export default function StatTile({
  value,
  label,
  source,
}: {
  value: string;
  label: string;
  source: string;
}) {
  return (
    <div className="flex flex-col gap-2 border-t border-rule pt-4 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0 lg:first:border-l-0 lg:first:pl-0">
      <p className="tabular font-display text-stat text-ink">{value}</p>
      <p className="text-small font-bold text-ink">{label}</p>
      <p className="text-caption text-muted">{source}</p>
    </div>
  );
}
