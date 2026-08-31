import Link from "next/link";

import HeroBackdrop from "@/components/ui/HeroBackdrop";
import { prettyUrl } from "@/lib/format";

/**
 * The run view keeps the landing page's photographic ground, cropped to a band. It is the
 * same place, quieter — the results are the subject here, not the pitch.
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
    <section className="relative isolate overflow-hidden">
      <HeroBackdrop variant="band" />

      <div className="relative z-10 mx-auto w-full max-w-6xl px-5 pb-12 pt-6 sm:px-8">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-ink-soft transition-colors hover:text-ink"
        >
          <span aria-hidden>←</span> webgraph
        </Link>

        <p className="mt-6 text-[11.5px] font-bold uppercase tracking-[0.16em] text-ink-soft">
          {mode === "site" ? "Whole-site extraction" : "Single-page extraction"}
        </p>

        <h1 className="mt-2 break-all font-display text-[clamp(1.9rem,5.5vw,3.2rem)] leading-[1.05]">
          {prettyUrl(url)}
        </h1>

        {children}
      </div>
    </section>
  );
}
