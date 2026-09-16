import UrlPrompt from "./UrlPrompt";

export default function Hero() {
  return (
    <section className="page-col max-md:pb-12 max-md:pt-12 md:pb-16 md:pt-20">
      <div className="grid grid-cols-12 gap-x-6 gap-y-10">
        <div className="max-lg:col-span-12 lg:col-span-8">
          <p className="text-label font-bold uppercase text-muted">
            Open-source · Runs locally · MIT
          </p>
          <h1 className="mt-5 font-display text-display text-ink">The honest web reader.</h1>
          <p className="measure-lede mt-6 text-body text-muted">
            Point it at a website. Every public page comes back as Markdown in the order a
            reader sees it, with a note of how each page was obtained — and a refusal, named,
            for every page it could not read.
          </p>
        </div>

        <div className="max-lg:col-span-12 lg:col-span-8 lg:col-start-3">
          <UrlPrompt />
          <p className="mt-3 text-caption text-muted lg:text-right">
            Runs on your machine. The only requests made are to the site you name.
          </p>
        </div>
      </div>
    </section>
  );
}
