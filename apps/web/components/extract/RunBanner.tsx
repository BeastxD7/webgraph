import { prettyUrl } from "@/lib/format";

/**
 * The run's title. The same ground as the landing page, quieter — the results are the
 * subject here, not the pitch. The site bar above it carries the way back.
 */
export default function RunBanner({
  url,
  mode,
  children,
}: {
  url: string;
  mode: "site" | "page";
  children?: React.ReactNode;
}) {
  return (
    <section className="page-col pb-10 pt-8 sm:pt-10">
      <p className="text-label font-bold uppercase text-muted">
        {mode === "site" ? "Whole-site extraction" : "Single-page extraction"}
      </p>

      <h1 className="mt-2 break-all font-display text-h1 text-ink">{prettyUrl(url)}</h1>

      {children}
    </section>
  );
}
