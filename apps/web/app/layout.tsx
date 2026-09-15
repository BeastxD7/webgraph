import type { Metadata, Viewport } from "next";
import { Instrument_Serif, JetBrains_Mono, Manrope } from "next/font/google";

import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";

import "./globals.css";

const display = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  display: "swap",
  variable: "--font-instrument-serif",
});

const sans = Manrope({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
  variable: "--font-manrope",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
  variable: "--font-jetbrains-mono",
});

export const metadata: Metadata = {
  title: {
    default: "webgraph — the honest web reader",
    template: "%s · webgraph",
  },
  description:
    "Point it at a website. Every public page comes back as Markdown in the order a reader " +
    "sees it, with a note of how each page was obtained — and a refusal, named, for every " +
    "page it could not read.",
  applicationName: "webgraph",
  keywords: [
    "web scraping",
    "content extraction",
    "markdown",
    "crawler",
    "reading order",
    "boilerplate removal",
  ],
  openGraph: {
    type: "website",
    title: "webgraph",
    description:
      "Every public page of a website as Markdown, in reading order, with provenance and named refusals.",
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f7f4" },
    { media: "(prefers-color-scheme: dark)", color: "#0e1310" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    // `suppressHydrationWarning`: the boot script below stamps `data-theme` on this element
    // before React runs, so the server markup and the first client render legitimately
    // differ by one attribute.
    <html
      lang="en"
      suppressHydrationWarning
      className={`${display.variable} ${sans.variable} ${mono.variable}`}
    >
      <head>
        {/* A plain synchronous script, as next-themes does it: it must run before first
            paint so a remembered theme does not flash the other one, and `next/script`'s
            beforeInteractive queue runs after DOMContentLoaded (measured). */}
        <script suppressHydrationWarning dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body className="flex min-h-dvh flex-col antialiased">
        <SiteHeader />
        <div className="flex-1">{children}</div>
        <SiteFooter />
      </body>
    </html>
  );
}
