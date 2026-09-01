.PHONY: help install api web dev test lint check check-clean bench bench-content check-responsive clean

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
	@echo "  make bench-routes  Score route discovery against a real-browser oracle"
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

bench-content:
	cd packages/engine && uv run --group bench python ../../benchmark/content_quality/run.py

bench-content-diff:
	cd packages/engine && uv run --group bench python ../../benchmark/content_quality/run.py --diff

bench-routes:
	cd packages/engine && uv run python ../../benchmark/route_discovery/run.py

bench-routes-quick:
	cd packages/engine && uv run python ../../benchmark/route_discovery/run.py --limit 10

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache apps/web/.next
