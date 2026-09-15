import Link from "next/link";

import { MEASURED } from "@/lib/benchmarks";

import { FOOTER_LINKS } from "./links";
import Wordmark from "./Wordmark";

/** The measured date without its "(evening)" qualifier, which belongs on the boards page. */
export const MEASURED_DAY = MEASURED.date.replace(/\s*\(.*\)$/, "");

export default function SiteFooter() {
  return (
    <footer className="mt-16 border-t border-rule sm:mt-24">
      <div className="page-col grid gap-8 py-10 text-small text-muted md:grid-cols-3 md:gap-12">
        <div className="flex flex-col gap-3">
          <Wordmark />
          <p className="measure-lede">
            An open-source extraction engine. It reports how it knows, and declines when it
            does not.
          </p>
        </div>

        <nav aria-label="Footer">
          <ul className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 md:grid-cols-2">
            {FOOTER_LINKS.map((item) => (
              <li key={item.label}>
                {item.external ? (
                  <a
                    href={item.href}
                    target="_blank"
                    rel="noreferrer"
                    className="hover:text-ink"
                  >
                    {item.label} <span aria-hidden>↗</span>
                  </a>
                ) : (
                  <Link href={item.href} className="hover:text-ink">
                    {item.label}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        </nav>

        <p className="text-caption md:text-right">
          Last measured {MEASURED_DAY} ·{" "}
          <code className="font-mono">main@{MEASURED.commit}</code>
        </p>
      </div>
    </footer>
  );
}
