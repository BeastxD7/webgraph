import { createFromSource } from "fumadocs-core/search/server";

import { source } from "@/lib/source";

/** Built-in full-text search over the docs, queried by the search dialog in the docs layout. */
export const { GET } = createFromSource(source, {
  language: "english",
});
