.PHONY: dev ci backend frontend build start stop lint test test-full test-concurrent test-perf test-e2e test-book-e2e test-book-content test-books-all test-v2 eval logs smoke luminary clean regen-api-types install docker-build docker-run

LUMINARY_PORT ?= 7820

clean:
	@echo "Stopping processes on Luminary ports (7820, 5173, 5174)..."
	@for port in 7820 5173 5174; do \
		pid=$$(lsof -ti :$$port 2>/dev/null); \
		if [ -n "$$pid" ]; then \
			echo "  killing PID $$pid on :$$port"; \
			kill -9 $$pid; \
		fi; \
	done
	@echo "Done."

dev:
	@echo "Starting backend and frontend dev servers..."
	@(cd backend && DATA_DIR="$(CURDIR)/.luminary" uv run uvicorn app.main:app --reload --port 7820) &
	@(cd frontend && npm run dev) &
	@wait

backend:
	cd backend && DATA_DIR="$(CURDIR)/.luminary" uv run uvicorn app.main:app --reload --port 7820

frontend:
	cd frontend && npm run dev

install:
	bash scripts/install.sh

build:
	@echo "Building production SPA (public tier, /api base)..."
	cd frontend && VITE_SURFACE_TIER=public VITE_API_BASE=/api npm run build

start:
	bash scripts/start.sh

docker-build:
	docker build -t luminary:latest .

docker-run:
	docker compose --profile ai up

stop:
	@pids=$$(lsof -ti :$(LUMINARY_PORT) 2>/dev/null); \
	if [ -z "$$pids" ]; then \
		echo "No Luminary app running on :$(LUMINARY_PORT)."; \
	else \
		echo "Gracefully stopping Luminary on :$(LUMINARY_PORT) (SIGTERM to $$pids)..."; \
		kill $$pids 2>/dev/null || true; \
		for i in 1 2 3 4 5 6 7 8 9 10; do \
			sleep 0.5; \
			pids=$$(lsof -ti :$(LUMINARY_PORT) 2>/dev/null); \
			[ -z "$$pids" ] && break; \
		done; \
		if [ -n "$$pids" ]; then \
			echo "  still alive after 5s; sending SIGKILL to $$pids"; \
			kill -9 $$pids 2>/dev/null || true; \
		fi; \
		echo "Stopped."; \
	fi

lint:
	cd backend && uv run ruff check .
	cd frontend && npx tsc --noEmit
	python3 scripts/check_manifest_schema.py
	python3 scripts/check_manifest_coverage.py
	bash scripts/check_powershell.sh

test:
	cd backend && uv run pytest

test-full:
	cd backend && uv run pytest tests/test_integration_full.py -v -m slow

test-concurrent:
	cd backend && uv run pytest tests/test_concurrent.py -v -m slow

test-perf:
	cd backend && uv run pytest tests/test_performance.py -v -m slow

test-e2e:
	cd backend && BACKEND_URL=$${BACKEND_URL:-http://localhost:7820} uv run pytest tests/test_e2e_upload.py -m e2e -v

test-book-e2e:
	cd backend && uv run pytest tests/test_e2e_book.py -v -m slow --timeout=700

test-book-content:
	cd backend && uv run pytest tests/test_book_content.py -v -m slow --timeout=900

test-books-all:
	@echo "Ingesting all 3 books once, then running all book tests..."
	cd backend && uv run pytest tests/test_diagnostics.py tests/test_book_content.py tests/test_e2e_book.py \
	  -v -m slow --timeout=2400

test-v2:
	@echo "Running V2 pipeline integration tests (requires 3 corpus books ingested)..."
	cd backend && uv run pytest tests/test_v2_pipeline.py -v -m slow --timeout=1800

smoke:
	@echo "Running smoke tests (requires backend on :7820)..."
	bash scripts/smoke/all.sh

eval:
	@echo "Running retrieval quality evals (backend must be running on :7820)..."
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset book --assert-thresholds
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset paper --assert-thresholds

luminary:
	bash scripts/luminary.sh

# Regenerate the Concept layer: wipe + rebuild higher-level themes from the entity graph
# (the real concept model, not 1:1 promotion). Run with the server STOPPED (needs the
# Kuzu lock + LLM, must not starve the live loop). Idempotent. DATA_DIR matches luminary.sh.
concepts:
	cd backend && DATA_DIR="$(CURDIR)/.luminary" uv run python -m app.scripts.regenerate_concepts

# Deprecated: naive 1:1 entity->concept promotion. Use `make concepts` instead.
backfill-concepts:
	cd backend && DATA_DIR="$(CURDIR)/.luminary" uv run python -m app.scripts.backfill_concepts

logs:
	bash scripts/dev-logs.sh

ci:
	@echo "Running CI checks..."
ifeq ($(shell uname -s)-$(shell uname -m),Darwin-x86_64)
	@echo "Intel Mac detected: running backend CI in Docker (lancedb has no x86_64 macOS wheel)..."
	docker build -q -t luminary-ci -f backend/Dockerfile.ci backend/
	docker run --rm luminary-ci
else
	cd backend && uv sync
	cd backend && uv run ruff check .
	cd backend && uv run python tools/layer_linter.py
	cd backend && uv run python tools/boundary_checker.py
	./scripts/check_public_import.sh
	cd backend && uv run pytest
endif
	python3 scripts/check_manifest_schema.py
	python3 scripts/check_manifest_coverage.py
	bash scripts/check_powershell.sh
	cd frontend && npm run build
	cd frontend && npx tsc --noEmit
	@echo "CI passed."

regen-api-types:
	cd frontend && npm run regen:api-types
