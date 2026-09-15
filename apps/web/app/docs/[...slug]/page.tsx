import type { Metadata } from "next";

import { DocPage, docMetadata } from "@/components/docs/DocPage";
import { source } from "@/lib/source";

type Props = Readonly<{ params: Promise<{ slug: string[] }> }>;

export default async function DocsSlugPage({ params }: Props) {
  const { slug } = await params;
  return <DocPage slug={slug} />;
}

export function generateStaticParams() {
  // The landing page has no segments and is served by app/docs/page.tsx.
  return source.generateParams().filter((entry) => entry.slug.length > 0);
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  return docMetadata(slug);
}
