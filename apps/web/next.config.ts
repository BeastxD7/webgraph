import type { NextConfig } from "next";
import { createMDX } from "fumadocs-mdx/next";

const config: NextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
  typescript: { ignoreBuildErrors: false },
};

// Fumadocs MDX compiles `content/docs` into the collection declared in `lib/source.ts`
// (its Macro API: `defineDocs` is rewritten by the bundler, so no generated `.source`
// directory and nothing to run before `tsc`). The transform is confined to `lib/` so it
// never touches the rest of the app; the pattern is anchored on the folder rather than the
// app root because Turbopack resolves rule globs from the workspace root (the lockfile's).
const withMDX = createMDX({
  macro: { include: ["**/lib/**/*.ts"] },
});

export default withMDX(config);
