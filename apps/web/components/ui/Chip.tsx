import type { ReactNode } from "react";

/**
 * A chip says one thing about the object beside it, in a word and a mark. The mark repeats
 * the word's meaning in form -- a filled dot for what is here, a hollow ring for what is not
 * yet -- so nothing is carried by colour alone (DESIGN.md §6, §7).
 */
export type ChipTone = "available" | "coming" | "measured" | "assumed" | "refused" | "plain";

const TONE: Record<ChipTone, string> = {
  available: "bg-accent-soft text-accent-ink",
  coming: "bg-transparent text-muted",
  measured: "bg-good-soft text-good",
  assumed: "bg-warn-soft text-warn",
  refused: "bg-bad-soft text-bad",
  plain: "bg-sunk text-muted",
};

export default function Chip({
  tone = "plain",
  children,
  className = "",
}: {
  tone?: ChipTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex h-[22px] items-center gap-1.5 rounded-pill px-2 text-caption font-semibold ${TONE[tone]} ${className}`}
    >
      {tone === "available" && <span aria-hidden className="size-2 rounded-full bg-accent" />}
      {tone === "coming" && (
        <span aria-hidden className="size-2 rounded-full border-[1.5px] border-faint" />
      )}
      {children}
    </span>
  );
}
