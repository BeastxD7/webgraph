/**
 * "This is LaTeX, not garbled text" -- shown next to the Markdown/Preview toggle whenever a
 * page's Markdown contains `$...$`/`$$...$$`. Reported live: raw LaTeX in the "Markdown" view
 * read as corrupted output rather than source syntax. The small (i) carries the one fact that
 * matters once it *is* rendered -- which renderer did it, since KaTeX and the site's own
 * renderer (often MathJax) can differ in what they support -- without cluttering every
 * formula with its own attribution.
 */
export default function MathBadge({ preview }: { preview: boolean }) {
  return (
    <span
      title={
        preview
          ? "Formulas are LaTeX ($...$ / $$...$$), typeset here with KaTeX."
          : "Formulas are written as LaTeX ($...$ / $$...$$), not HTML -- that's the raw source a math-aware renderer typesets. Switch to Preview to see it rendered here."
      }
      className="inline-flex items-center gap-1 rounded-full bg-sunk px-2 py-0.5 text-[11.5px] font-semibold text-ink-soft"
    >
      Σ LaTeX math
      {preview && (
        <span
          title="Rendered using the KaTeX renderer (katex.org)."
          aria-label="Rendered using the KaTeX renderer"
          className="inline-flex size-3.5 items-center justify-center rounded-full border border-current text-[9px] leading-none"
        >
          i
        </span>
      )}
    </span>
  );
}
