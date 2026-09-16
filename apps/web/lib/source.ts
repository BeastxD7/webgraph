import { loader } from "fumadocs-core/source";
import { defineDocs } from "fumadocs-mdx/macro";

/**
 * The documentation collection: every `.mdx` under `content/docs`, with `meta.json`
 * files ordering the sidebar. Plain `.md` files are deliberately not compiled, which
 * keeps `content/docs/_authoring.md` (the writers' guide) out of the routes.
 */
const docs = defineDocs({
  dir: "content/docs",
  docs: {
    files: ["**/*.mdx"],
  },
});

export const source = loader({
  baseUrl: "/docs",
  source: docs.toFumadocsSource(),
});
