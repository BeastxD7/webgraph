import type { Metadata } from "next";

import Step2Fetch from "@/components/landing/how/Step2Fetch";

export const metadata: Metadata = { title: "Fetch-twice playground", robots: { index: false, follow: false } };

/** Step 2's illustration on its own, in a stage the size of the landing page's, looping. */
export default function FetchTwicePlaygroundPage() {
  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <p className="font-mono text-caption uppercase tracking-wide text-muted">UI playground</p>
      <h1 className="mt-2 text-h2 font-bold text-ink">Step 2 — fetch twice</h1>
      <div className="mt-10 flex h-[66vh] max-h-[38rem] items-center justify-center rounded-xl border border-rule bg-ground">
        <Step2Fetch />
      </div>
    </main>
  );
}
