# The web app.
#
# Three things shape this image, each worth stating rather than discovering:
#
# 1. The build context is the *repository root*, not this directory. The pnpm workspace
#    (`pnpm-workspace.yaml`) and its lockfile live there, and pnpm needs both to install
#    correctly even though every application file lives under `apps/web`. Build it as:
#      docker build -f apps/web/Dockerfile -t webgraph-web .
#    `apps/web/Dockerfile.dockerignore` -- not the root `.dockerignore`, which is written
#    for the *other* Dockerfile and excludes `apps/web` entirely -- keeps that context small.
#
# 2. `NEXT_PUBLIC_API_BASE` and `WEBGRAPH_API_PROXY` are both build `ARG`s, not runtime
#    `ENV`s, and both have to be. `NEXT_PUBLIC_API_BASE` is inlined into the JavaScript
#    bundle at build time (`content/docs/deployment/configuration.mdx`); setting it only at
#    `docker run` would ship a bundle asking every visitor's own machine for the API.
#    `WEBGRAPH_API_PROXY` looks like it should be a runtime concern -- next.config.ts reads
#    `process.env` for it -- but Next.js resolves `rewrites()` once, into
#    `.next/routes-manifest.json`, at `next build`, and never re-reads it at `next start`.
#    Confirmed directly: a container built without it set answers `/api/*` with Next's own
#    404 page no matter what's set at `docker run`; rebuilt with it set, the same route
#    proxies correctly. The default target, `/`, pairs with `NEXT_PUBLIC_API_BASE=/` so the
#    container can proxy `/api/*` to a backend chosen at *build* time instead -- the "one
#    origin" mode `docker-compose.yml` uses.
#
# 3. This is a full `node_modules` image, not Next.js's `output: "standalone"` trace.
#    Standalone was tried first, for the same "install once, copy only the minimum" shape
#    as the root Dockerfile -- but under this project's pnpm workspace, its file tracer
#    silently dropped two of Next.js's own runtime dependencies (`@swc/helpers`, then
#    `@next/env`, discovered one after the other by running the traced server and reading
#    which `Cannot find module` came back each time) even with `outputFileTracingRoot` set
#    to the workspace root. A tracer that must be patched by hand, dependency by dependency,
#    as they turn up empty at container start is not something to ship. A full
#    `pnpm install --prod` uses the exact same dependency resolution `pnpm build` already
#    proves works, at the cost of a larger image (node_modules, not a pruned trace) -- a
#    trade this project takes deliberately for a Docker image that starts correctly the
#    first time, every time.
#
# Build:  docker build -f apps/web/Dockerfile \
#           --build-arg WEBGRAPH_API_PROXY=http://host.docker.internal:8000 \
#           -t webgraph-web .
# Run:    docker run -p 3000:3000 webgraph-web

FROM node:24-slim AS base
RUN corepack enable
WORKDIR /app

# Manifests only, so this layer -- and the dependency install after it -- survives every
# source change. `apps/web/package.json` first: pnpm's workspace resolution needs it
# alongside the root manifest even though nothing in it changes independently of the lock.
FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile

# A second install, production dependencies only, so the runtime stage never carries
# eslint, typescript or the type packages `pnpm build` needed but `next start` never will.
FROM base AS deps-prod
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile --prod

FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/web/node_modules ./apps/web/node_modules
COPY . .

ARG NEXT_PUBLIC_API_BASE=/
ARG WEBGRAPH_API_PROXY=""
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
ENV WEBGRAPH_API_PROXY=${WEBGRAPH_API_PROXY}
# Telemetry needs a writable $HOME to record its own opt-out; this build runs as root only
# in this stage, but off is off regardless of who could have written the file.
ENV NEXT_TELEMETRY_DISABLED=1

RUN pnpm --filter @webgraph/web build

FROM base AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root from here on, matching the API image's posture: this process renders whatever
# Markdown and links a crawled page contained, by the time it reaches here already inert,
# but the container boundary should not depend on that alone.
RUN groupadd --gid 10001 webgraph && useradd --uid 10001 --gid webgraph --create-home webgraph

COPY --from=deps-prod --chown=webgraph:webgraph /app/node_modules ./node_modules
COPY --from=deps-prod --chown=webgraph:webgraph /app/apps/web/node_modules ./apps/web/node_modules
COPY --from=builder --chown=webgraph:webgraph /app/apps/web/.next ./apps/web/.next
COPY --from=builder --chown=webgraph:webgraph /app/apps/web/public ./apps/web/public
COPY --from=builder --chown=webgraph:webgraph /app/apps/web/package.json ./apps/web/package.json
COPY --from=builder --chown=webgraph:webgraph /app/apps/web/next.config.ts ./apps/web/next.config.ts

USER webgraph
WORKDIR /app/apps/web
EXPOSE 3000

CMD ["./node_modules/.bin/next", "start", "--port", "3000", "--hostname", "0.0.0.0"]
