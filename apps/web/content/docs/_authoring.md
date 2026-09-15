# Writing documentation

This file is not a page: the docs collection compiles `.mdx` files only, so a plain `.md`
here is never routed or listed. Everything else under `content/docs/` is.

## Where a page goes

`content/docs/<section>/<name>.mdx` is served at `/docs/<section>/<name>`; a folder's
`index.mdx` is the section's own page (`/docs/<section>`), and the section's entry in the
sidebar links to it. The seven sections and their order are fixed by
`content/docs/meta.json`; each section's `meta.json` orders the pages inside it:

```json
{
  "title": "Crawling",
  "pages": ["route-discovery", "politeness", "..."]
}
```

List pages by file name without the extension, and leave `index` out (listing it turns the
section's own page into an ordinary child item). `"..."` appends whatever is not listed,
in alphabetical order, so a new page shows up without editing `meta.json`; move it into
the list when its position matters. `"---Label---"` inserts a separator, and
`"[Text](https://...)"` an external link. Once a `pages` list names anything, a page it
does not name is still built and reachable by URL, just absent from the sidebar.

## Frontmatter

```mdx
---
title: Route discovery
description: One sentence, shown under the title and in search results and link previews.
---
```

`title` is required and is the sidebar label and the `<h1>`; do not repeat it as a
heading in the body. `description` is optional but every page should have one. `full: true`
widens the page by hiding the table of contents, for a wide table or diagram.

Headings start at `##`. The table of contents is built from `##` and `###`.

## Components

Available on every page without an import:

| Component | Use |
|---|---|
| `<Callout title="..." type="info">` | An aside. `type` is `info` (default), `warn`, `error`, `success` or `idea`. |
| `<Cards>` / `<Card title="..." href="...">` | A grid of link cards; the body of a `Card` is its description. |
| `<Tabs items={["pnpm", "uv"]}>` / `<Tab value="pnpm">` | Alternatives; the `value` of each `Tab` matches an entry in `items`. |
| `<Steps>` / `<Step>` | A numbered procedure; put a `###` heading first in each `Step`. |
| `<Accordions>` / `<Accordion title="...">` | Collapsed detail that most readers can skip. |

Fenced code blocks are highlighted by language and get a copy button; add `title="file.py"`
after the language for a file tab. Standard Markdown tables render with tabular numerals,
so figures line up.

Anything else from `fumadocs-ui/components/*` can be registered in
`apps/web/components/docs/mdx-components.tsx`.

## Links

Between docs pages, link by URL from the site root: `[the API](/docs/api)`. A relative
file path also works (`[politeness](./politeness.mdx)`) and is rewritten to the page's
URL, which survives a section being renamed. Link to the rest of the site the same way
(`/benchmarks`, `/how-it-works`). Anchors are the heading text in lower case with hyphens:
`/docs/api#streaming`.

Images live in `apps/web/public/` and are referenced from the root (`/docs/crawl.png`);
record anything bundled in `apps/web/public/ASSETS.md`.

## Checking a page

`pnpm web:dev` from the repository root, then open `/docs/...`. Content changes reload
in place; `pnpm web:build` catches a broken MDX expression or an unknown component before
CI does.
