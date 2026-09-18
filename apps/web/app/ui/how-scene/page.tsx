import type { Metadata } from "next";

import HowScenePlayground from "./HowScenePlayground";

export const metadata: Metadata = { title: "How-scene playground", robots: { index: false, follow: false } };

export default function HowScenePlaygroundPage() {
  return <HowScenePlayground />;
}
