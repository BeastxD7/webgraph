import Image from "next/image";

import heroImage from "@/public/hero-palouse.jpg";

/**
 * The photographic hero ground.
 *
 * The scrim is the load-bearing part. The photograph's own sky band is thin, so a
 * top-down wash of the page ground manufactures the pale field the display type needs
 * while leaving the hills legible below it. A second wash at the bottom returns the
 * section to the page colour so the hero ends without a hard edge.
 */
export default function HeroBackdrop({
  variant = "full",
  priority = false,
}: {
  /** `band` is the short crop used above a run; it frames on the foreground hills, since a
   *  200px slice of the upper third is just haze. */
  variant?: "full" | "band";
  /** Set on the landing page, where this is the largest contentful paint. */
  priority?: boolean;
}) {
  const band = variant === "band";

  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <Image
        src={heroImage}
        alt=""
        fill
        priority={priority}
        sizes="100vw"
        placeholder="blur"
        className={`scale-105 object-cover saturate-[1.06] ${
          band ? "object-[center_88%]" : "object-[center_38%]"
        }`}
      />
      <div
        className="absolute inset-0"
        style={{
          background: band
            ? "linear-gradient(180deg, var(--color-haze) 0%, color-mix(in srgb, var(--color-haze) 88%, transparent) 45%, color-mix(in srgb, var(--color-haze) 62%, transparent) 100%)"
            : "linear-gradient(180deg, var(--color-haze) 0%, color-mix(in srgb, var(--color-haze) 94%, transparent) 26%, color-mix(in srgb, var(--color-haze) 72%, transparent) 44%, color-mix(in srgb, var(--color-haze) 30%, transparent) 62%, transparent 82%)",
        }}
      />
      <div
        className={`absolute inset-x-0 bottom-0 ${band ? "h-20" : "h-64"}`}
        style={{
          background: "linear-gradient(0deg, var(--color-haze) 0%, var(--color-haze) 12%, transparent 100%)",
        }}
      />
    </div>
  );
}
