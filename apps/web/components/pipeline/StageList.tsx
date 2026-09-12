import { STAGES } from "@/lib/pipeline";

/**
 * The crawl as a numbered rail.
 *
 * Numbered because this genuinely is a sequence -- stage four cannot run before stage three,
 * and the number is the reader's place in it rather than decoration. Each stage repeats the
 * same four parts in the same order (what it does, what it takes and gives, the point worth
 * pulling out, what goes wrong), so a reader who has read one knows where to look in the rest.
 */
export default function StageList() {
  return (
    <ol className="mt-14 flex flex-col">
      {STAGES.map((stage, index) => (
        <li key={stage.id} id={stage.id} className="grid scroll-mt-20 grid-cols-[2.6rem_1fr] gap-x-5 sm:grid-cols-[3.2rem_1fr] sm:gap-x-7">
          <div className="flex flex-col items-center">
            <span className="grid size-8 shrink-0 place-items-center rounded-full bg-leaf-600 font-mono text-[12px] font-bold text-white">
              {index + 1}
            </span>
            {index < STAGES.length - 1 ? (
              <span aria-hidden className="my-2 w-px flex-1 bg-line-strong" />
            ) : null}
          </div>

          <div className={`min-w-0 ${index < STAGES.length - 1 ? "pb-12" : ""}`}>
            <h2 className="font-display text-[clamp(1.35rem,3vw,1.7rem)] leading-tight">
              {stage.title}
            </h2>

            {stage.body.map((paragraph) => (
              <p key={paragraph.slice(0, 40)} className="mt-3 max-w-[64ch] text-[15px] leading-relaxed text-ink-soft">
                {paragraph}
              </p>
            ))}

            <div className="mt-5 flex flex-wrap items-center gap-2">
              <span className="rounded-full border border-line bg-sunk px-2.5 py-1 font-mono text-[11px] text-ink-faint">
                in: {stage.takes}
              </span>
              {stage.gives.map((item) => (
                <span
                  key={item}
                  className="rounded-full bg-leaf-50 px-2.5 py-1 font-mono text-[11px] text-leaf-700"
                >
                  out: {item}
                </span>
              ))}
            </div>

            {stage.rescues ? (
              <ul className="mt-5 flex flex-col gap-3 border-l-2 border-leaf-300 pl-4">
                {stage.rescues.map((rescue) => (
                  <li key={rescue.what} className="max-w-[62ch]">
                    <span className="text-[14px] font-bold">{rescue.what}</span>
                    <span className="block text-[13.5px] leading-relaxed text-ink-soft">
                      {rescue.why}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}

            {stage.note ? (
              <p className="mt-5 max-w-[62ch] rounded-xl border border-line bg-surface px-4 py-3 text-[13.5px] leading-relaxed text-ink-soft shadow-card">
                {stage.note}
              </p>
            ) : null}

            {stage.failures ? (
              <div className="mt-5 border-l-2 border-clay pl-4">
                <h3 className="font-mono text-[11px] font-semibold uppercase tracking-[0.09em] text-clay">
                  {stage.failureTitle ?? "When it goes wrong"}
                </h3>
                <dl className="mt-3 flex flex-col gap-2.5">
                  {stage.failures.map((failure) => (
                    <div
                      key={failure.when}
                      className="grid gap-x-5 gap-y-0.5 sm:grid-cols-[minmax(0,11rem)_1fr]"
                    >
                      <dt className="text-[13.5px] font-bold">{failure.when}</dt>
                      <dd className="max-w-[56ch] text-[13.5px] leading-relaxed text-ink-soft">
                        {failure.then}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
