import type { NextConfig } from "next";
import { createMDX } from "fumadocs-mdx/next";

// `WEBGRAPH_API_PROXY=http://127.0.0.1:8000` makes this server forward `/api/*` to the
// API, so a build with `NEXT_PUBLIC_API_BASE=/` is one origin: one tunnel or one domain
// serves both, and CORS never enters. `afterFiles`, so the app's own `/api/search` (docs
// search) keeps winning. Read at build *and* start; set it for both.
const apiProxy = process.env.WEBGRAPH_API_PROXY?.replace(/\/+$/, "");

const config: NextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
  typescript: { ignoreBuildErrors: false },
  async rewrites() {
    if (!apiProxy) return [];
    return { afterFiles: [{ source: "/api/:path*", destination: `${apiProxy}/api/:path*` }] };
  },
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
