.PHONY: help install api web dev test lint check check-clean bench bench-live bench-fidelity bench-random-web bench-content bench-union bench-union-fetch bench-reading-order check-responsive clean docker-build docker-run docker-build-web compose-up compose-down deploy-api deploy-web

help:
	@echo "webgraph — development commands"
	@echo ""
	@echo "  make install   Install Python and Node dependencies"
	@echo "  make api       Run the API on :8000"
	@echo "  make web       Run the frontend on :3000"
	@echo "  make test      Run every test suite"
	@echo "  make check     Lint, type-check and test everything"
	@echo "  make check-clean   Verify a cold install the way CI does"
	@echo "  make lint      Lint and type-check everything"
	@echo "  make bench     Score schema extraction against the benchmark corpus"
	@echo "  make bench-content Score main-content extraction against three other tools"
	@echo "  make bench-live    Score a fixed set of live sites against Chromium's own text (diff two runs)"
	@echo "  make bench-fidelity  Whole-page Markdown against Chromium on old/ugly pages: recall, extra, order, structure"
	@echo "  make bench-random-web  The same measure on 300 pages nobody picked (benchmark/random_web/sample-2026-09.txt)"
	@echo "  make bench-routes  Score route discovery against a real-browser oracle"
	@echo "  make bench-union   Score union block placement (needs bench-union-fetch once)"
	@echo "  make bench-reading-order  Score reading order vs a DOM walk"
	@echo ""
	@echo "  make docker-build  Build the API container"
	@echo "  make docker-run    Run it on :8080"
	@echo "  make docker-build-web  Build the web container"
	@echo "  make compose-up    Build and run both containers on one VM (see docs/deployment/vm.mdx)"
	@echo "  make compose-down  Stop them"
	@echo "  make deploy-api    Deploy the API to Cloud Run (see docs/DEPLOY.md)"
	@echo "  make deploy-web    Deploy the frontend to Vercel"
	@echo ""
	@echo "Run 'make api' and 'make web' in two terminals for the full stack."

install:
	uv sync --all-packages --group dev
	uv run --package webgraph playwright install chromium
	pnpm install

api:
	uv run --package webgraph-api uvicorn webgraph_api.main:app --reload --host 127.0.0.1 --port 8000

web:
	pnpm web:dev

test:
	cd packages/engine && uv run pytest tests -q
	uv run --package webgraph-api pytest apps/api/tests -q

lint:
	cd packages/engine && uv run ruff check . && uv run mypy
	uv run --package webgraph-api ruff check apps/api
	uv run --package webgraph-api mypy --config-file apps/api/pyproject.toml apps/api/src
	pnpm web:typecheck
	pnpm web:lint

bench:
	cd packages/engine && uv run webgraph bench ../../benchmark/corpus-v0

check: lint test
	@echo ""
	@echo "Lint, types and tests pass. Two things this does NOT cover:"
	@echo "  make check-responsive   needs the web app running on :3000"
	@echo "  make bench-content      hits the network and needs the 'bench' group"

check-clean:
	@# CI installs from a cold tree; a warm node_modules once hid a broken install
	@# through 26 consecutive red runs. This reproduces what CI actually does.
	@set -e; \
	dir=$$(mktemp -d); \
	echo "cloning to $$dir"; \
	git clone -q . $$dir; \
	cd $$dir && pnpm install --frozen-lockfile && pnpm web:typecheck && pnpm web:lint && pnpm web:build; \
	echo "clean install OK"; rm -rf $$dir

check-responsive:
	uv run --package webgraph python tools/check_responsive.py

bench-live:
	uv run --package webgraph python benchmark/live/run.py --out live-suite.json

bench-fidelity:
	uv run --package webgraph python benchmark/fidelity/run.py --out fidelity.json

bench-random-web:
	uv run --package webgraph python benchmark/fidelity/run.py --sites benchmark/random_web/sample-2026-09.txt --out random-web.json
	uv run --package webgraph python benchmark/random_web/report.py random-web.json

bench-content:
	cd packages/engine && uv run --group bench python ../../benchmark/content_quality/run.py

bench-content-diff:
	cd packages/engine && uv run --group bench python ../../benchmark/content_quality/run.py --diff

bench-routes:
	cd packages/engine && uv run python ../../benchmark/route_discovery/run.py

bench-routes-quick:
	cd packages/engine && uv run python ../../benchmark/route_discovery/run.py --limit 10

# Union-by-adjacency placement. Two phases: `fetch` hits the network once per site and
# caches both representations; `score` runs offline over that cache, so the ablation sweep
# can be repeated without refetching.
bench-union-fetch:
	uv run --package webgraph python benchmark/union_adjacency/run.py fetch

bench-union:
	uv run --package webgraph python benchmark/union_adjacency/run.py score

# Reading order: geometric recovery vs a DOM walk, scored on geometric axioms rather than
# on either method's own output. Offline; uses the same page cache as bench-union.
bench-reading-order:
	uv run --package webgraph python benchmark/reading_order/run.py

# Deployment. See docs/DEPLOY.md for what these flags mean and why.
GCP_REGION ?= us-central1
GCP_SERVICE ?= webgraph-api
ALLOWED_ORIGINS ?= http://localhost:3000

docker-build:
	docker build -t $(GCP_SERVICE) .

docker-run:
	docker run --rm -p 8080:8080 \
	  -e WEBGRAPH_ALLOWED_ORIGINS=$(ALLOWED_ORIGINS) \
	  $(GCP_SERVICE)

deploy-api:
	@# --max-instances 1 is load-bearing: the graph cache and crawl slots are in-process,
	@# so a second instance answers /api/site/context from a process that never crawled.
	gcloud run deploy $(GCP_SERVICE) \
	  --source . \
	  --region $(GCP_REGION) \
	  --allow-unauthenticated \
	  --execution-environment gen2 \
	  --cpu 2 --memory 4Gi \
	  --max-instances 1 \
	  --concurrency 20 \
	  --timeout 3600 \
	  --set-env-vars WEBGRAPH_ALLOWED_ORIGINS=$(ALLOWED_ORIGINS)

deploy-web:
	@# NEXT_PUBLIC_API_BASE is inlined at build time; set it in Vercel before this runs.
	cd apps/web && pnpm dlx vercel --prod

# Both containers, one VM: see docs/deployment/vm.mdx. WEBGRAPH_API_PROXY is a *build*
# argument (next.config.ts's rewrites() are resolved once at `next build`, never re-read
# at start), which is why it is passed here and not as compose `environment:`.
docker-build-web:
	docker build -f apps/web/Dockerfile \
	  --build-arg NEXT_PUBLIC_API_BASE=/ \
	  --build-arg WEBGRAPH_API_PROXY=http://api:8080 \
	  -t webgraph-web .

compose-up:
	docker compose up --build -d

compose-down:
	docker compose down

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache apps/web/.next
