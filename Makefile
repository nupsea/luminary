.PHONY: dev ci backend frontend lint test test-full logs

dev:
	@echo "Starting backend and frontend dev servers..."
	@(cd backend && uv run uvicorn app.main:app --reload --port 8000) &
	@(cd frontend && npm run dev) &
	@wait

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

lint:
	cd backend && uv run ruff check .
	cd frontend && npx tsc --noEmit

test:
	cd backend && uv run pytest

test-full:
	cd backend && uv run pytest tests/test_integration_full.py -v -m slow

logs:
	bash scripts/dev-logs.sh

ci:
	@echo "Running CI checks..."
	cd backend && uv sync
	cd backend && uv run ruff check .
	cd backend && uv run python tools/layer_linter.py
	cd backend && uv run python tools/boundary_checker.py
	cd backend && uv run pytest
	cd frontend && npm run build
	cd frontend && npx tsc --noEmit
	@echo "CI passed."
