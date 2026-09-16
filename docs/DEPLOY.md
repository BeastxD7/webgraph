# Deploying webgraph

Two processes, deployed two different ways, because they have opposite requirements.

| | What it is | Where it goes |
|---|---|---|
| `apps/web` | A static-ish Next.js client that only ever talks to the API from the browser | Vercel free tier |
| `apps/api` | FastAPI, with a headless Chromium inside it, streaming a crawl for minutes | A container host |

The frontend is the easy half and is not discussed much below. The backend is the whole
problem.

---

## Why the backend cannot go on a serverless platform

Three constraints, in the order that they eliminate options:

1. **`POST /api/site/stream` holds one HTTP response open for minutes.** The endpoint emits
   an SSE frame per page as the crawl walks the site. Every function platform — Vercel
   Functions, Netlify, Lambda behind API Gateway, Cloudflare Workers — either caps the
   response duration or buffers it. A buffered stream is not a stream.
2. **Chromium runs in-process.** `Strategy.UNION` renders every page to measure its layout;
   that is where reading-order recovery comes from. So the host needs Docker, roughly a
   gigabyte of memory before the Python process is counted, and a real CPU core.
3. **Exactly one instance.** `_graphs`, `_crawl_slots`, `_crawl_pool` and `GraphStore` are
   all in-process or local-disk state. With two instances a crawl completes on A and
   `/api/site/context` answers 404 from B, intermittently, which is the worst kind of bug
   to debug. Pin max instances to 1.

A fourth constraint appears the moment the frontend is on HTTPS: the backend must be too,
or the browser blocks the request as mixed content. That rules out "a free VM with an IP
address" unless a reverse proxy is put in front of it.

## What is actually free, as of September 2026

| Host | Verdict |
|---|---|
| **Google Cloud Run** | **Works.** Always-free quota, real streaming, 60-minute request ceiling, scale-to-zero. Needs a card on the billing account. |
| Hugging Face Spaces | **No.** Docker Spaces now require a paid plan; only static Spaces are free. Was the obvious pick a year ago. |
| Render free / Koyeb free | **No.** 512 MB and 0.1 vCPU. Chromium wants more than that on its own. |
| Fly.io | **No.** The free tier ended in 2024; the trial is 2 VM-hours. |
| Modal | Possible, but the app has to be restructured around `@modal.asgi_app()`. $30/month of credits rather than a standing quota. |

Verify claims like these before trusting them — free tiers change faster than
documentation does.

### The cost arithmetic on Cloud Run

The always-free monthly quota is 2M requests, 180,000 vCPU-seconds and 360,000 GiB-seconds.
At the container size below (2 vCPU, 4 GiB) both compute lines run out at the same place:

```
180,000 vCPU-s ÷ 2 vCPU = 25 hours
360,000 GiB-s  ÷ 4 GiB  = 25 hours
```

So roughly **25 hours of active crawling per month**, and nothing at all while idle, since
CPU is only allocated while a request is in flight. A demo shared with a few people does
not come close. A public link that gets posted somewhere might.

---

## Deploying the API to Cloud Run

The free quota only applies in `us-central1`, `us-east1` and `us-west1`. Pick one.

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com

gcloud run deploy webgraph-api \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --execution-environment gen2 \
  --cpu 2 --memory 4Gi \
  --max-instances 1 \
  --concurrency 20 \
  --timeout 3600 \
  --set-env-vars WEBGRAPH_ALLOWED_ORIGINS=http://localhost:3000
```

Each flag, and why it is not the default:

- `--execution-environment gen2` — gen1 runs under gVisor, which intercepts syscalls
  Chromium needs. gen2 is a full kernel.
- `--memory 4Gi` — four browsers at ~150 MB, plus page documents held in memory during a
  crawl, plus the Python process.
- `--max-instances 1` — constraint 3. Without it Cloud Run will happily start a second
  instance under load and split the graph cache in half.
- `--concurrency 20` — one instance serving many callers, which is the intent. The API's own
  `WEBGRAPH_MAX_CONCURRENT_CRAWLS` is what actually bounds the expensive work.
- `--timeout 3600` — the maximum. A crawl that reaches it is cut off mid-stream, which is
  why `WEBGRAPH_MAX_PAGES` matters.

`--set-env-vars` starts with localhost because the Vercel URL does not exist yet. It gets
corrected in the last step.

## Deploying the frontend to Vercel

In the Vercel project settings, set **Root Directory** to `apps/web`. Vercel detects the
pnpm workspace at the repository root and installs from there.

Set the API URL **before the first build**:

```bash
vercel env add NEXT_PUBLIC_API_BASE production
# paste the https://webgraph-api-....run.app URL that gcloud printed
vercel --prod
```

`NEXT_PUBLIC_*` variables are inlined into the bundle at build time, not read at runtime.
A build that runs without it keeps the `http://127.0.0.1:8000` default and then asks each
*visitor's own machine* for the API. Changing the variable later requires a redeploy, not
just a save. (`lib/api.ts` detects this specific mistake and says so in the error, because
the symptom is indistinguishable from a backend that is simply down.)

## Then close the loop

The API is still only accepting requests from localhost. Point it at the real frontend:

```bash
gcloud run services update webgraph-api --region us-central1 \
  --set-env-vars WEBGRAPH_ALLOWED_ORIGINS=https://your-app.vercel.app
```

Do not use `*`. This service fetches arbitrary URLs on the caller's behalf; an open CORS
policy hands every page on the internet a fetch proxy that runs inside your network.

---

## Environment reference

Everything is read at process start. Nothing has to be set for local development.

| Variable | Default | What it does |
|---|---|---|
| `WEBGRAPH_ALLOWED_ORIGINS` | the dev frontend | Comma-separated CORS origins. |
| `WEBGRAPH_MAX_PAGES` | `0` (no ceiling) | Hard ceiling on pages per crawl, whatever a client asks. The engine's own default is 500 pages and an hour (`CRAWL_MAX_PAGES`, `CRAWL_MAX_SECONDS`), but a client may ask for `0` -- "until the frontier is exhausted" -- so on a shared host this should still be set. |
| `WEBGRAPH_MAX_CONCURRENCY` | `0` (unbounded) | Ceiling on per-crawl worker concurrency. The request model allows 12; a two-core container should not. |
| `WEBGRAPH_MAX_CONCURRENT_CRAWLS` | `2` in the image, `3` otherwise | Whole-site crawls in flight across all callers. |
| `WEBGRAPH_MAX_CONCURRENT_RENDERS` | `2` | Single-page render requests in flight. |
| `WEBGRAPH_MAX_BROWSERS` | `6` (`4` in the image) | Live Chromium instances process-wide, ~150 MB each. |
| `WEBGRAPH_CHROMIUM_ARGS` | empty (set in the image) | Extra Chromium flags. Containers need `--no-sandbox --disable-dev-shm-usage`. |
| `WEBGRAPH_BLOCK_PRIVATE_HOSTS` | on for the API | Refuse loopback, private and link-local addresses. |
| `WEBGRAPH_ALLOW_PRIVATE_HOSTS` | unset | Opt out of the above, for pointing a local API at a local site. Wins if both are set. |
| `WEBGRAPH_GRAPH_DIR` | `~/.cache/webgraph` | Where finished site graphs are written. |

## Before sharing the link

The API fetches whatever URL it is handed and returns the body. On a cloud host that
includes the instance metadata service, which serves credentials over plain HTTP to
anything that asks. `webgraph.fetch.guard` refuses those addresses and is on by default in
the API — but a misconfigured deployment looks perfectly healthy, so check it rather than
assume it:

```bash
API=https://webgraph-api-....run.app

# Must report "private_hosts_blocked": true and a non-zero "max_pages".
curl -s $API/api/health

# Must be refused: 502, with "non-public" in the detail.
curl -s -o /dev/null -w '%{http_code}\n' -X POST $API/api/text \
  -H 'content-type: application/json' \
  -d '{"url":"http://169.254.169.254/latest/meta-data/","render":false}'

# Must be refused from an origin that is not in the allow-list.
curl -s -D- -o /dev/null -X OPTIONS $API/api/text \
  -H 'Origin: https://evil.example' \
  -H 'Access-Control-Request-Method: POST' | grep -i access-control-allow-origin
```

The guard resolves each hostname and rejects non-public answers, on every redirect hop.
It does not defend against DNS rebinding — a name that answers publicly on the first lookup
and privately on the second. Closing that needs the connection pinned to the checked
address; it is documented in `guard.py` rather than fixed, because it is a much narrower
hole than the unguarded default and nobody is targeting a demo.

---

## Running the container locally first

Worth doing before spending a deploy cycle on it.

```bash
make docker-build
make docker-run          # http://localhost:8080
curl -s localhost:8080/api/health
```

The build downloads Chromium, so the first one takes a few minutes; after that only the
last two layers rebuild.

## The alternative that needs no account at all

If a card on a Google Cloud billing account is the blocker, run the API on the machine you
already have and give it a public HTTPS address:

```bash
make api
cloudflared tunnel --url http://127.0.0.1:8000
```

That prints a `https://something.trycloudflare.com` URL to use as `NEXT_PUBLIC_API_BASE`.
Set `WEBGRAPH_ALLOWED_ORIGINS` to the Vercel URL and `WEBGRAPH_MAX_PAGES` to something
sane before doing this — the local default is unbounded, and this is a public address.

The trade is obvious: your laptop is now the server, and the link dies when it sleeps.
