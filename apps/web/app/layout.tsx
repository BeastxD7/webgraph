import type { Metadata, Viewport } from "next";
import { Instrument_Serif, JetBrains_Mono, Manrope } from "next/font/google";

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
  display: "swap",
  variable: "--font-manrope",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-jetbrains-mono",
});

export const metadata: Metadata = {
  title: {
    default: "webgraph — every page of any website, as clean Markdown",
    template: "%s · webgraph",
  },
  description:
    "webgraph detects a site's technology stack, discovers every public route, and extracts " +
    "rich Markdown with reading order recovered from the rendered layout rather than guessed " +
    "from the HTML.",
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
      "Every page of any website, as clean Markdown — with reading order recovered from layout.",
  },
};

export const viewport: Viewport = {
  themeColor: "#f5f7f3",
  colorScheme: "light",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${sans.variable} ${mono.variable}`}
    >
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
