import type { Metadata } from "next";

import SettingsPanel from "@/components/settings/SettingsPanel";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";

export const metadata: Metadata = {
  title: "Settings",
  robots: { index: false },
};

export default function SettingsPage() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto w-full max-w-4xl px-5 pb-20 sm:px-8">
        <header className="pt-6 pb-8">
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-faint">Settings</p>
          <h1 className="mt-2 font-display text-[2rem] leading-tight tracking-tight">
            How your runs behave
          </h1>
          <p className="mt-3 max-w-[62ch] text-[14px] leading-relaxed text-ink-soft">
            Every default comes from <code className="rounded bg-sunk px-1 py-0.5 font-mono text-[12.5px]">webgraph/config.py</code>.
            Change a value here and it is sent with every run from this browser; clear it and
            the file&rsquo;s value applies again. Settings the API does not let a request change
            are listed at the bottom, read-only, with the file as the place to change them.
          </p>
        </header>
        <SettingsPanel />
      </main>
      <SiteFooter />
    </>
  );
}
