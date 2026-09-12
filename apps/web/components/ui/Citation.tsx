import type { PageEvent } from "@/lib/api";

/**
 * Where a page came from, in one line.
 *
 * Every page a crawl reports should answer "and how do you know this is here". The three
 * facts that answer it are the method, the page that produced it, and the words on the link
 * -- and the last of those is what makes it a citation rather than a reference, because it
 * is the only part a person can recognise.
 *
 * The root says so plainly instead of showing an empty provenance. Nothing pointed at it,
 * and that is a fact about the crawl rather than a gap in the record.
 */
const VIA: Record<string, string> = {
  seed: "the address this crawl started from",
  sitemap: "listed in the sitemap of",
  link: "linked from",
};

export default function Citation({
  citation,
  className = "",
}: {
  citation: PageEvent["citation"];
  className?: string;
}) {
  if (!citation) return null;

  if (citation.via === "seed") {
    return (
      <span className={`font-mono text-[11px] text-ink-faint ${className}`}>
        {VIA.seed}
      </span>
    );
  }

  return (
    <span className={`font-mono text-[11px] text-ink-faint ${className}`}>
      {VIA[citation.via] ?? citation.via}{" "}
      {citation.found_on ? (
        <a
          href={citation.found_on}
          target="_blank"
          rel="noreferrer"
          className="underline underline-offset-2 hover:text-ink-soft"
        >
          {citation.found_on.replace(/^https?:\/\//, "")}
        </a>
      ) : (
        "an earlier page"
      )}
      {citation.anchor && (
        <>
          {" "}
          as <span className="text-ink-soft">&ldquo;{citation.anchor}&rdquo;</span>
        </>
      )}
    </span>
  );
}
