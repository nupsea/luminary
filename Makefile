.PHONY: dev ci backend frontend lint test

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

ci:
	@echo "Running CI checks..."
	cd backend && uv run ruff check .
	cd backend && uv run pytest
	@echo "CI not yet fully configured (frontend checks added in S00b)"
