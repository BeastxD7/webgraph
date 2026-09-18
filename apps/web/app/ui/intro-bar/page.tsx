import type { Metadata } from "next";

import IntroBarPlayground from "./IntroBarPlayground";

export const metadata: Metadata = { title: "Intro-bar playground", robots: { index: false, follow: false } };

export default function IntroBarPlaygroundPage() {
  return <IntroBarPlayground />;
}
