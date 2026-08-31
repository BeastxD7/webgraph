import UrlPrompt from "./UrlPrompt";

export default function Hero() {
  return (
    <div className="relative z-10 mx-auto flex w-full max-w-6xl flex-col items-center px-5 pb-36 pt-10 text-center sm:px-8 sm:pb-48 sm:pt-16">
      <p className="text-[11.5px] font-bold uppercase tracking-[0.18em] text-ink-soft">
        Open-source extraction engine
      </p>

      <h1 className="mt-5 max-w-3xl text-balance font-display text-[clamp(2.6rem,8vw,4.6rem)] leading-[1.02] tracking-[-0.015em]">
        Every page of a website,
        <br />
        as <em className="italic text-leaf-700">clean Markdown</em>
      </h1>

      <p className="mt-6 max-w-xl text-pretty text-[15px] leading-relaxed text-ink-soft sm:text-base">
        webgraph detects the stack, enumerates every public route, and extracts rich Markdown
        — with reading order recovered from the rendered layout rather than guessed from the
        HTML.
      </p>

      <div className="mt-12 w-full sm:mt-16">
        <UrlPrompt />
      </div>
    </div>
  );
}
