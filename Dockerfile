# The API, with a browser in it.
#
# Two things make this image awkward, and both are worth stating rather than discovering:
#
# 1. Chromium is not an optional extra. The engine's whole-site strategy renders every page
#    to measure its layout, so the image has to carry a browser and its shared libraries --
#    around 400 MB of the final size. A slim Python base plus `playwright install --with-deps`
#    is the only reliable way to get those libraries right; hand-listing apt packages works
#    until a Chromium release adds one.
#
# 2. Dependencies and the browser are installed before any source is copied. Application
#    code changes on every commit and dependencies change monthly, so ordering it this way
#    means a code change rebuilds in seconds instead of re-downloading Chromium.
#
# Build:  docker build -t webgraph-api .
# Run:    docker run -p 8080:8080 -e WEBGRAPH_ALLOWED_ORIGINS=http://localhost:3000 webgraph-api

FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.9.29 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    # Outside $HOME, because the runtime user's home is not guaranteed writable and a
    # browser that cannot find itself fails at the first render rather than at build time.
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

# Manifests only. `--no-install-workspace` installs the third-party tree without needing the
# workspace source, so this layer -- and the Chromium download after it -- survives every
# code change.
COPY pyproject.toml uv.lock ./
COPY packages/engine/pyproject.toml packages/engine/README.md packages/engine/
COPY apps/api/pyproject.toml apps/api/
RUN uv sync --frozen --package webgraph-api --no-dev --no-install-workspace

# Driven from the venv that was just built, so the browser matches the exact Playwright
# version in uv.lock. Installing a floating `playwright` here instead would fetch a browser
# build the pinned client may not speak to. `--with-deps` runs apt-get and needs root.
RUN /app/.venv/bin/playwright install --with-deps chromium \
    && chmod -R a+rX /opt/playwright \
    && rm -rf /var/lib/apt/lists/*

COPY packages/engine packages/engine
COPY apps/api apps/api
RUN uv sync --frozen --package webgraph-api --no-dev

# Defaults chosen for a 2 vCPU / 4 GiB container. Every one is overridable at deploy time;
# these are the values that keep the container inside that budget.
ENV PORT=8080 \
    # Refuse loopback and link-local fetches. The API defaults to this anyway; setting it
    # explicitly means the posture is visible in `docker inspect` rather than implied.
    WEBGRAPH_BLOCK_PRIVATE_HOSTS=1 \
    # A shared host cannot let one caller crawl a site until its frontier is exhausted.
    WEBGRAPH_MAX_PAGES=50 \
    WEBGRAPH_MAX_CONCURRENCY=4 \
    WEBGRAPH_MAX_CONCURRENT_CRAWLS=2 \
    WEBGRAPH_MAX_CONCURRENT_RENDERS=2 \
    # ~150 MB resident each. Four is the ceiling that fits alongside the Python process.
    WEBGRAPH_MAX_BROWSERS=4 \
    # Chromium's own sandbox needs kernel capabilities a container is not granted, and the
    # default 64 MB /dev/shm is too small for a heavy page -- the renderer crashes rather
    # than degrading. The container boundary is the sandbox here.
    WEBGRAPH_CHROMIUM_ARGS="--no-sandbox --disable-dev-shm-usage --disable-gpu" \
    # Site graphs persist here so a restart does not discard minutes of crawling. On a
    # scale-to-zero host this is a cache, not storage: it goes away with the instance.
    WEBGRAPH_GRAPH_DIR=/tmp/webgraph-graphs

# Non-root from here on. Chromium runs whatever JavaScript the crawled page contains, so the
# process hosting it should not own the filesystem it runs on.
RUN useradd --create-home --uid 10001 webgraph && chown -R webgraph:webgraph /app
USER webgraph

EXPOSE 8080

# uvicorn straight from the venv rather than through `uv run`, which would try to re-sync at
# container start -- needing the network and a writable tree that this user does not have.
#
# One worker, deliberately: the graph cache, the crawl slots and the crawl thread pool are
# all in-process state, so a second worker would answer /api/site/context from a process that
# never ran the crawl. Scale by making the container bigger, not by adding workers.
#
# Shell form so $PORT expands -- Cloud Run and most container hosts inject it.
CMD exec /app/.venv/bin/uvicorn webgraph_api.main:app \
    --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-graceful-shutdown 5
