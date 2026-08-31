const REPO = "https://github.com/BeastxD7/webgraph";

export default function SiteFooter() {
  return (
    <footer className="mx-auto w-full max-w-6xl px-5 pb-12 pt-16 sm:px-8">
      <div className="flex flex-col gap-6 border-t border-line pt-8 text-[13px] text-ink-soft sm:flex-row sm:items-start sm:justify-between">
        <p className="max-w-md">
          <strong className="font-extrabold text-ink">webgraph</strong> — an open-source
          extraction engine. Reading order is recovered from the rendered layout; site chrome
          is identified by cross-page analysis rather than per-page heuristics.
        </p>

        <div className="flex flex-col gap-1.5 sm:items-end">
          <a href={REPO} target="_blank" rel="noreferrer" className="hover:text-ink">
            Source on GitHub
          </a>
          {/* CC BY 4.0 requires attribution wherever the work is used, not only in the
              repository, so the credit lives in the page itself. */}
          <p className="text-ink-faint">
            Hero photograph{" "}
            <a
              className="underline underline-offset-2 hover:text-ink-soft"
              href="https://commons.wikimedia.org/wiki/File:PalouseFromSteptoeButteMay2023-2.jpg"
              target="_blank"
              rel="noreferrer"
            >
              “The Palouse from Steptoe Butte”
            </a>{" "}
            by Caleb Riston,{" "}
            <a
              className="underline underline-offset-2 hover:text-ink-soft"
              href="https://creativecommons.org/licenses/by/4.0/"
              target="_blank"
              rel="noreferrer"
            >
              CC BY 4.0
            </a>
            .
          </p>
        </div>
      </div>
    </footer>
  );
}
