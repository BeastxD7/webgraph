.PHONY: help install api web dev test lint bench clean

help:
	@echo "webgraph — development commands"
	@echo ""
	@echo "  make install   Install Python and Node dependencies"
	@echo "  make api       Run the API on :8000"
	@echo "  make web       Run the frontend on :3000"
	@echo "  make test      Run every test suite"
	@echo "  make lint      Lint and type-check everything"
	@echo "  make bench     Score extraction against the benchmark corpus"
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

bench-routes:
	cd packages/engine && uv run python ../../benchmark/route_discovery/run.py

bench-routes-quick:
	cd packages/engine && uv run python ../../benchmark/route_discovery/run.py --limit 10

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache apps/web/.next
