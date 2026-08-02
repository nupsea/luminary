.PHONY: dev ci backend frontend build start stop lint test test-full test-concurrent test-perf test-e2e test-book-e2e test-book-content test-books-all test-v2 eval eval-d2l eval-d2l-rerank eval-d2l-gen eval-topics golden-d2l logs smoke luminary clean regen-api-types verify-router install release docker-build docker-run stage stage-payload stage-python stage-ollama verify-stage desktop-dev desktop-app desktop-adhoc

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

# --- macOS desktop bundle -----------------------------------------------
# Stage the payload, the relocatable Python runtime and the bundled inference
# server into build/stage, which becomes Contents/Resources in the .app.

stage: stage-payload stage-python stage-ollama

stage-payload:
	bash scripts/macos/stage_payload.sh

stage-python:
	bash scripts/macos/stage_python.sh

stage-ollama:
	bash scripts/macos/stage_ollama.sh

verify-stage:
	bash scripts/macos/verify_stage.sh
	bash scripts/macos/verify_ollama.sh

# Run the shell against build/stage without bundling. Requires `make stage`.
desktop-dev:
	cd src-tauri && LUMINARY_STAGE="$(CURDIR)/build/stage" cargo run --release

# Unsigned Luminary.app. The payload is copied in with ditto rather than Tauri's
# resource copier, which does not preserve the interpreter's bin/python symlinks.
DESKTOP_APP = src-tauri/target/release/bundle/macos/Luminary.app

TAURI = $(CURDIR)/frontend/node_modules/.bin/tauri

desktop-app:
	cd src-tauri && $(TAURI) build --bundles app --config tauri.conf.json
	ditto build/stage "$(DESKTOP_APP)/Contents/Resources"
	@echo "built $(DESKTOP_APP)"

# Sign and package locally with the ad-hoc identity. Exercises enumeration,
# ordering and every gate; the result is not notarizable and Gatekeeper rejects
# it, so it proves the pipeline rather than producing a release.
desktop-adhoc: desktop-app
	bash scripts/macos/sign.sh $(DESKTOP_APP) --adhoc
	bash scripts/macos/verify_signed.sh $(DESKTOP_APP) --adhoc
	bash scripts/macos/dmg.sh $(DESKTOP_APP) $(shell sed -n 's/^version = "\(.*\)"/\1/p' backend/pyproject.toml | head -1) --adhoc

build:
	@echo "Building production SPA (public mode, /api base)..."
	cd frontend && VITE_LUMINARY_MODE=public VITE_API_BASE=/api npm run build

start:
	bash scripts/start.sh

release:
	@v=$$(sed -n 's/^version = "\(.*\)"/\1/p' backend/pyproject.toml | head -1); \
	if [ -n "$$(git status --porcelain)" ]; then \
		echo "Working tree is dirty — commit before tagging."; exit 1; \
	fi; \
	echo "Tagging v$$v — triggers release.yml (source tarball) and"; \
	echo "release-macos-app.yml (signed, notarized DMG). Both attach to the same release."; \
	git tag -a "v$$v" -m "Luminary $$v" && git push origin "v$$v"

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

# D2L technical-corpus retrieval (HR@5/MRR). Backend on :7820 with d2l ingested.
# Retrieval-only (--judge-model "" disables the RAGAS judge) so it runs in seconds.
eval-d2l:
	@echo "Retrieval eval on the d2l technical corpus (HR@5/MRR, no judge)..."
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset d2l --backend-url http://localhost:7820 --judge-model "" --assert-thresholds

# Same dataset WITH the cross-encoder reranker — compare HR@5/MRR against `eval-d2l`.
eval-d2l-rerank:
	@echo "Retrieval eval on d2l WITH cross-encoder reranking (A/B vs eval-d2l)..."
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset d2l --backend-url http://localhost:7820 --judge-model "" --rerank

# Generation quality (faithfulness, answer-relevance) via a LOCAL Ollama judge.
# Slow (one judge call per question); separate from the fast HR/MRR target above.
eval-d2l-gen:
	@echo "Generation eval on d2l (RAGAS, local judge — slow)..."
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset d2l --backend-url http://localhost:7820 --judge-model ollama/qwen2.5:14b-instruct

# Topic-generation eval (precision/recall/F1 + junk-rate). Uses the backend venv.
eval-topics:
	@echo "Topic-generation eval on d2l..."
	uv run --project $(CURDIR)/backend python evals/run_topic_eval.py --dataset d2l --backend-url http://localhost:7820 --assert-thresholds

# Regenerate the d2l golden Q&A (ONE-TIME, needs OPENAI_API_KEY + Ollama). Overwrites d2l.jsonl.
golden-d2l:
	@echo "Regenerating d2l golden (GPT-5.4 generate + cross-model verify)..."
	uv run --project $(CURDIR)/backend python evals/generate_golden.py \
		--source DATA/books/d2l_dive_into_deep_learning.md \
		--out evals/golden/d2l.jsonl \
		--generator-model openai/gpt-5.4 \
		--verify-models openai/gpt-5.1 ollama/qwen2.5:14b-instruct \
		--verify-axes answerable answer_correct --target 50

luminary:
	bash scripts/luminary.sh

# Regenerate the Concept layer: wipe + rebuild higher-level themes from the entity graph
# (the real concept model, not 1:1 promotion). Run with the server STOPPED (needs the
# Kuzu lock + LLM, must not starve the live loop). Idempotent. DATA_DIR matches luminary.sh.
concepts:
	cd backend && DATA_DIR="$(CURDIR)/.luminary" uv run python -m app.scripts.regenerate_concepts

# Inspect-only: run the concept pipeline nodes (no persist) and dump the diagnostics
# report (entities kept/dropped by type, clusters, proposed themes). Server STOPPED.
concepts-dryrun:
	cd backend && DATA_DIR="$(CURDIR)/.luminary" uv run python -m app.scripts.regenerate_concepts --dry-run

# Deprecated: naive 1:1 entity->concept promotion. Use `make concepts` instead.
backfill-concepts:
	cd backend && DATA_DIR="$(CURDIR)/.luminary" uv run python -m app.scripts.backfill_concepts

# Apply pending migrations to the dev database. The server does this itself on boot;
# this is for applying a revision without a restart.
db-migrate:
	cd backend && DATA_DIR="$(CURDIR)/.luminary" uv run alembic upgrade head

# Generate a revision from the diff between models.py and the migrations.
#   make db-revision m="add foo to bar"
# Deliberately autogenerated against a THROWAWAY database built from the migrations,
# never the dev one. A long-lived dev database carries orphan tables from removed
# features and TEXT-vs-VARCHAR noise from the legacy ALTERs; pointed at it, autogenerate
# emits drop_table() for real user tables and ~126 spurious type changes.
db-revision:
	@test -n "$(m)" || { echo 'usage: make db-revision m="describe your change"'; exit 1; }
	@cd backend && D=$$(mktemp -d) && \
		DATA_DIR=$$D uv run alembic upgrade head >/dev/null && \
		DATA_DIR=$$D uv run alembic revision --autogenerate -m "$(m)"; \
		rm -rf $$D

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

# Client-side routing smoke test in a real browser. Needs the app already
# running (make luminary) -- it drives the live UI, so it is not part of `make
# ci`. playwright-core is installed --no-save: a dev-only tool, deliberately
# kept out of package.json so CI never pulls a browser.
verify-router:
	@cd frontend && (node -e "require.resolve('playwright-core')" 2>/dev/null \
		|| (echo "Installing playwright-core (not saved to package.json)..." && npm install --no-save playwright-core))
	cd frontend && LUMINARY_URL=$${LUMINARY_URL:-http://localhost:5173} LUMINARY_API=$${LUMINARY_API:-http://localhost:$(LUMINARY_PORT)} node scripts/verify-router.mjs
