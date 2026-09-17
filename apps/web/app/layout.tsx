import type { Metadata, Viewport } from "next";
import { Instrument_Serif, JetBrains_Mono, Manrope } from "next/font/google";

import SiteChrome from "@/components/site/SiteChrome";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";

import "katex/dist/katex.min.css";
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
  // Absolute URLs for og:image and friends. Without a base Next falls back to
  // http://localhost:3000, and a link preview (Discord, Slack, X) then asks the reader's own
  // machine for the picture and shows nothing. Set NEXT_PUBLIC_SITE_URL at build time to the
  // public origin the site is served from; the default is the dev server.
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/+$/, "") || "http://localhost:3000"),
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
    siteName: "webgraph",
    title: "webgraph — the honest web reader",
    description:
      "Every public page of a website as Markdown, in reading order, with provenance and named refusals.",
  },
  twitter: { card: "summary_large_image" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f6f9" },
    { media: "(prefers-color-scheme: dark)", color: "#080c14" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    // `suppressHydrationWarning`: the boot script below stamps `data-theme` on this element
    // before React runs, and the docs theme switch writes a class onto it the same way, so
    // the server markup and the first client render legitimately differ there.
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
        <SiteChrome>
          <SiteHeader />
        </SiteChrome>
        <div className="flex-1">{children}</div>
        <SiteChrome>
          <SiteFooter />
        </SiteChrome>
      </body>
    </html>
  );
}
