.PHONY: dev ci backend frontend lint test test-full test-concurrent test-perf test-e2e test-book-e2e test-book-content test-books-all test-v2 eval logs smoke luminary clean

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

lint:
	cd backend && uv run ruff check .
	cd frontend && npx tsc --noEmit

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
	cd evals && uv run python run_eval.py --dataset book --assert-thresholds
	cd evals && uv run python run_eval.py --dataset paper --assert-thresholds

luminary:
	bash scripts/luminary.sh

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
	cd backend && uv run pytest
endif
	cd frontend && npm run build
	cd frontend && npx tsc --noEmit
	@echo "CI passed."
