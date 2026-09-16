import type { Metadata } from "next";

import { DocPage, docMetadata } from "@/components/docs/DocPage";

export default function DocsIndexPage() {
  return <DocPage />;
}

export function generateMetadata(): Metadata {
  return docMetadata();
}
