import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { createRelativeLink } from "fumadocs-ui/mdx";
import { DocsBody, DocsDescription, DocsPage, DocsTitle } from "fumadocs-ui/layouts/docs/page";

import { getMDXComponents } from "@/components/docs/mdx-components";
import { source } from "@/lib/source";

/**
 * One documentation page, by its slug segments (none for the landing page). Shared by
 * `app/docs/page.tsx` and `app/docs/[...slug]/page.tsx`: the two routes exist instead of
 * one optional catch-all because typed routes only admit `/docs` itself as a static route.
 */
export function DocPage({ slug }: Readonly<{ slug?: string[] }>) {
  const page = source.getPage(slug);
  if (!page) notFound();

  const MDX = page.data.body;

  return (
    <DocsPage toc={page.data.toc} full={page.data.full}>
      <DocsTitle>{page.data.title}</DocsTitle>
      <DocsDescription>{page.data.description}</DocsDescription>
      <DocsBody>
        <MDX
          components={getMDXComponents({
            // Lets a page link to a sibling by file path (`./crawling.mdx`) as well as by URL.
            a: createRelativeLink(source, page),
          })}
        />
      </DocsBody>
    </DocsPage>
  );
}

export function docMetadata(slug?: string[]): Metadata {
  const page = source.getPage(slug);
  if (!page) notFound();

  return {
    title: page.data.title,
    description: page.data.description,
  };
}
