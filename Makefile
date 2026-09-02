.PHONY: require-docker require-compose-release docker-stop docker-down docker-run-host-ollama dev ci backend frontend build start stop lint test test-full test-concurrent test-perf test-e2e test-book-e2e test-book-content test-books-all test-v2 eval eval-intent eval-ingest eval-gen eval-variance prompt-dump eval-models eval-matrix eval-summary eval-routing eval-flashcards golden-flashcards eval-all eval-d2l eval-d2l-rerank eval-d2l-gen eval-topics golden-d2l golden-paper golden-legal golden-play golden-study golden-thoughts logs smoke luminary clean regen-api-types verify-router install release docker-build docker-run stage stage-payload stage-python stage-ollama verify-stage check-stage desktop-dev desktop-app desktop-adhoc desktop-test

# Where the dev backend listens; `make dev` starts it here.
BACKEND_URL ?= http://localhost:7820

# The text model every eval target judges with. One variable, not six copies:
# `make eval-gen EVAL_TEXT_MODEL=ollama/llama3.2` switches the whole suite.
# A machine with a single model uses it for answering AND judging -- legal, and
# recorded as `self_judged` because a judge is not neutral about its own output.
# The vision model is resolved by the backend (Settings), never by the eval, and
# is recorded per run; `make eval-models` prints both before anything runs.
EVAL_TEXT_MODEL ?= ollama/qwen2.5:14b-instruct

LUMINARY_PORT ?= 7820

models:  ## what the current model configuration costs on this machine
	@cd backend && uv run python -c "\
from app.services.model_router import residency_report, warn_if_configuration_exceeds_host; \
r = residency_report(); \
print(f\"profile {r['profile']}  host {r['host_ram_gb']}GB  keeps {r['max_resident']} loaded\"); \
[print(f\"  {role:<11} {v['model']:<28} {v['resident_gb'] or '?'}GB\") for role, v in r['roles'].items()]; \
print(f\"  resident: {r['resident_count']} model(s), {r['resident_gb']}GB\"); \
w = warn_if_configuration_exceeds_host(); \
[print(f'  WARNING: {line}') for line in w] or print('  no warnings'); \
print('  (.env + registry defaults; a model chosen in Settings is stored in the'); \
print('   database and only shows at GET /settings/models on a running server)')"

# Was: `lsof -ti :$$port` then an immediate `kill -9`. That query matches
# clients as well as listeners, so it force-killed browser tabs pointed at the
# app, and -9 skips the shutdown that releases the Kuzu lock. See free_port.sh.
clean:
	@echo "Stopping processes on Luminary ports (7820, 5173, 5174)..."
	@sh scripts/free_port.sh 7820 5173 5174
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

# The desktop shell's own tests. Needs macOS: the crate does not build anywhere
# else, which is why ordinary `make ci` (ubuntu) cannot cover it.
# fmt first, and in the same order CI runs it: the desktop-shell job checks
# formatting before it tests, so a local gate without it reports green on a
# branch CI will reject -- which is exactly how it got rejected.
desktop-test:
	cd src-tauri && cargo fmt --check && cargo test && cargo clippy --all-targets -- -D warnings

# Run the shell against build/stage without bundling. Requires `make stage`.
desktop-dev:
	cd src-tauri && LUMINARY_STAGE="$(CURDIR)/build/stage" cargo run --release

# Unsigned Luminary.app. The payload is copied in with ditto rather than Tauri's
# resource copier, which does not preserve the interpreter's bin/python symlinks.
DESKTOP_APP = src-tauri/target/release/bundle/macos/Luminary.app

TAURI = $(CURDIR)/frontend/node_modules/.bin/tauri

# Everything the shell refuses to start without. Kept in step with REQUIRED in
# src-tauri/src/stage.rs, which checks the same list at runtime.
STAGE_REQUIRED = surface-manifest.json python/bin/python3.13 backend/app frontend ollama/ollama

# `ditto` copies a partial stage without complaint, producing an .app that
# launches and then cannot start. Note this gate cannot catch the other route to
# the same broken bundle -- running `tauri build` directly, which skips the ditto
# below entirely. The shell checks the same list at runtime for that reason.
check-stage:
	@missing=""; \
	for piece in $(STAGE_REQUIRED); do \
	    [ -e "build/stage/$$piece" ] || missing="$$missing $$piece"; \
	done; \
	if [ -n "$$missing" ]; then \
	    echo "build/stage is incomplete, missing:$$missing"; \
	    echo "run 'make stage' first"; \
	    exit 1; \
	fi
	@stale="$$(find backend/app frontend/dist -newer build/stage/surface-manifest.json -type f 2>/dev/null | head -3)"; \
	if [ -n "$$stale" ]; then \
	    echo "build/stage is older than your source, e.g.:"; \
	    echo "$$stale" | sed 's/^/    /'; \
	    echo "run 'make stage-payload' first, or the bundle ships the previous code"; \
	    exit 1; \
	fi
	@echo "stage complete and current"

desktop-app: check-stage
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

# WITH_MEDIA=1 adds ffmpeg and the transcriber (GPL, opt-in; see the Dockerfile).
# docker-run gets it through compose's own ${WITH_MEDIA} interpolation; this
# target builds directly, so it has to pass the arg itself or the flag is
# silently ignored on exactly one of the two documented ways to build.
WITH_MEDIA ?= 0

# Every docker target below fails the same way on a machine without a working
# daemon, and the bare failure is unhelpful: `docker: command not found` with a
# make Error 127, arriving AFTER this file has printed "Using host Ollama at
# :11434" -- which reads like the run started. Check the three things separately,
# because they fail independently: the CLI, the daemon, and the compose v2
# subcommand (every compose target here uses `docker compose`, not
# `docker-compose`). They run in that order for the reasons noted at each.
#
# Only the ABSENT cases are fatal. A daemon that is merely stopped is a state
# this target can fix, so it starts Docker Desktop (or colima) and waits, rather
# than making you run one command and re-run make. DOCKER_AUTOSTART=0 opts out --
# set it where a build should never launch a GUI app. The wait has to be generous
# and it has to end: Docker Desktop cold-starts a Linux VM, and a version too old
# for the host macOS hangs instead of failing, which is what the timeout catches.
DOCKER_AUTOSTART ?= 1
DOCKER_WAIT_SECS ?= 120

# Docker Desktop installs /usr/local/bin/docker and its compose plugin the FIRST
# TIME IT SUCCESSFULLY RUNS, through a privileged helper. Until that happens
# `docker` is not on PATH at all even though Docker is installed -- the failure
# reads as "not installed" when it is really "never started", which is a
# different fix. Fall back to the CLI inside the app bundle so this target can
# start Desktop instead of telling you to install what you already have.
# Appended, not prepended: a properly linked docker always wins over the bundle.
DOCKER_APP_BIN := /Applications/Docker.app/Contents/Resources/bin
ifneq ($(wildcard $(DOCKER_APP_BIN)/docker),)
export PATH := $(PATH):$(DOCKER_APP_BIN)
endif
require-docker:
	@command -v docker >/dev/null 2>&1 \
		|| { echo "No docker CLI found -- not on PATH, and no Docker.app to fall"; \
		     echo "back to. Install Docker Desktop:"; \
		     echo "   https://www.docker.com/products/docker-desktop/"; \
		     echo "or a lighter daemon:"; \
		     echo "   brew install colima docker docker-compose && colima start"; exit 1; }
	@docker info >/dev/null 2>&1 && exit 0; \
	if [ "$(DOCKER_AUTOSTART)" != "1" ]; then \
		echo "docker is installed but the daemon is not answering, and"; \
		echo "DOCKER_AUTOSTART=0. Start it yourself, then retry."; exit 1; \
	fi; \
	if [ "$$(uname -s)" = "Darwin" ] && [ -d /Applications/Docker.app ]; then \
		starter="Docker Desktop"; \
		open -g -a Docker \
			|| { echo "Could not launch Docker Desktop."; exit 1; }; \
	elif command -v colima >/dev/null 2>&1; then \
		starter="colima"; \
		colima start || { echo "'colima start' failed."; exit 1; }; \
	else \
		echo "docker is installed but the daemon is not answering, and there"; \
		echo "is nothing here to start it (no Docker.app, no colima)."; \
		echo "Start your daemon and retry -- on Linux:"; \
		echo "   sudo systemctl start docker"; exit 1; \
	fi; \
	printf "Daemon down; started %s, waiting up to %ss" "$$starter" "$(DOCKER_WAIT_SECS)"; \
	i=0; \
	while [ $$i -lt $(DOCKER_WAIT_SECS) ]; do \
		if docker info >/dev/null 2>&1; then echo " -- up."; exit 0; fi; \
		printf "."; sleep 2; i=$$((i+2)); \
	done; \
	echo ""; \
	echo "$$starter did not come up within $(DOCKER_WAIT_SECS)s."; \
	echo "It may be too old for this macOS, or wedged. Check it with:"; \
	echo "   docker info"; exit 1
# Compose is checked LAST, not alongside the CLI: starting Desktop is what
# installs the v2 plugin, so a machine that has never run it fails this check for
# a reason the step above already fixed.
	@docker compose version >/dev/null 2>&1 \
		|| { echo "The docker daemon is up, but this CLI has no 'docker compose'"; \
		     echo "(v2) subcommand:"; \
		     echo "   $$(docker --version 2>&1)"; \
		     echo "Every compose target here uses v2, not the docker-compose binary."; \
		     echo "Upgrade Docker Desktop, or: brew install docker-compose"; exit 1; }

# The build toolchain: compose AND buildx. Both live in the Docker Desktop
# bundle, so a stale Desktop fails here in two different places, one at a time --
# a current compose still refuses to build against buildx 0.5.1 with "compose
# build requires buildx 0.17.0 or later", arriving only after the Ollama probes
# have printed and the build has started.
#
# A pre-release compose is not a supported configuration here, and this is a
# separate gate from require-docker on purpose: it blocks the RUN targets only.
# Stopping and tearing down must keep working on a broken compose -- refusing to
# let someone shut the stack down because their compose is old is the wrong
# failure.
#
# 2.0.0-beta.4 creates the container and then never starts it, in BOTH attached
# and detached mode, so `make docker-run` parks at "Container luminary_app_1
# Created" and hangs indefinitely -- measured at 6min attached and 3min20s with
# -d before being killed, container still in Created both times. The same beta
# also refused to select any service until --profile ai was passed explicitly
# (see docker-run-host-ollama). Two independent breakages in one version is
# enough to stop guessing.
require-compose-release: require-docker
	@v="$$(docker compose version --short 2>/dev/null)"; \
	case "$$v" in \
		*alpha*|*beta*|*rc*) \
			if [ "$(ALLOW_PRERELEASE_COMPOSE)" = "1" ]; then \
				echo "warning: docker compose $$v is a pre-release; ALLOW_PRERELEASE_COMPOSE=1 set."; \
			else \
				echo "docker compose $$v is a pre-release, and this one does not work:"; \
				echo "it creates the container and never starts it, so the run hangs"; \
				echo "with nothing to show for it."; \
				echo "Upgrade Docker Desktop (Settings -> Software updates), or:"; \
				echo "   brew install docker-compose"; \
				echo "To run anyway: make $(MAKECMDGOALS) ALLOW_PRERELEASE_COMPOSE=1"; \
				exit 1; \
			fi ;; \
	esac
	@bx="$$(docker buildx version 2>/dev/null | sed -n 's/.*v\([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -1)"; \
	[ -n "$$bx" ] || { echo "docker buildx is missing; compose needs it to build."; \
	                   echo "   brew install docker-buildx"; exit 1; }; \
	maj=$${bx%%.*}; min=$${bx#*.}; \
	if [ "$$maj" -eq 0 ] && [ "$$min" -lt 17 ]; then \
		echo "docker buildx $$bx is too old -- compose build needs 0.17.0 or later."; \
		echo "Docker Desktop bundles buildx, so an old Desktop fails here even with"; \
		echo "a current compose. Upgrade Docker Desktop, or override just this plugin:"; \
		echo "   brew install docker-buildx"; \
		echo "   mkdir -p ~/.docker/cli-plugins"; \
		echo "   ln -sfn $$(brew --prefix 2>/dev/null || echo /usr/local)/opt/docker-buildx/bin/docker-buildx ~/.docker/cli-plugins/docker-buildx"; \
		exit 1; \
	fi

docker-build: require-docker
	docker build --build-arg WITH_MEDIA=$(WITH_MEDIA) -t luminary:latest .

# OLLAMA_URL pinned, not left to the ambient environment. The compose file now
# interpolates it (so the host-Ollama target below can move it), which means a
# shell that exports OLLAMA_URL for `make dev` -- 127.0.0.1, the loopback of the
# machine, not of the container -- would otherwise reach in here and point the
# container at itself.
docker-run: require-compose-release
	OLLAMA_URL=http://ollama:11434 docker compose --profile ai up --build

# Same stack, but inference runs on the HOST instead of in the compose network.
# On a Mac, Docker Desktop is a Linux VM: the `ai` profile puts Ollama inside it,
# where it shares a capped CPU and memory allowance with the app container --
# which is also running the embedder, reranker and entity model. A measured 91.07s
# start-up probe on an i7-8850H paid NO model load at all; those seconds were
# contention for 8 vCPUs. Moving inference out gives it the whole machine, and is
# the only latency lever measured so far that costs no answer quality.
#
# Ollama must listen beyond loopback or the container cannot reach it: it binds
# 127.0.0.1 by default, and `host.docker.internal` arrives from the bridge.
#   OLLAMA_HOST=0.0.0.0:11434 ollama serve
#
# `--profile ai ... --no-deps app`, not a bare `docker compose up`. Every service
# in this file carries a profile, so with none selected Compose 2.0.0-beta.4 built
# nothing and exited with "no service selected". Enabling `ai` is what makes `app`
# a selectable service at all; naming it and passing --no-deps is what leaves the
# ollama sidecars out. Do not drop --no-deps to "simplify" this -- the ollama
# container comes back and takes the VM's CPU with it, which is the whole point.
docker-run-host-ollama: require-compose-release
	@command -v ollama >/dev/null || { echo "Install Ollama first: https://ollama.com/download"; exit 1; }
	@curl -sf http://localhost:11434/api/tags >/dev/null \
		|| { echo "Ollama is not answering on :11434. Start it with:"; \
		     echo "   OLLAMA_HOST=0.0.0.0:11434 ollama serve"; exit 1; }
	@if command -v lsof >/dev/null 2>&1; then \
		lsof -nP -iTCP:11434 -sTCP:LISTEN 2>/dev/null \
			| grep -qE "TCP \*:11434|TCP 0\.0\.0\.0:11434" \
		|| { echo "Ollama is listening on loopback only, so the container cannot reach it."; \
		     echo "The curl above passes over 127.0.0.1 and proves nothing about the bridge:"; \
		     echo "that is exactly the case this check exists to catch. Restart it as:"; \
		     echo "   OLLAMA_HOST=0.0.0.0:11434 ollama serve"; exit 1; }; \
	fi
	@m=$${LITELLM_DEFAULT_MODEL:-ollama/qwen3.5:4b}; m=$${m#ollama/}; \
	curl -sf http://localhost:11434/api/tags | grep -q "\"$$m\"" \
		|| { echo "Host Ollama is up but does not have $$m."; \
		     echo "The ollama-pull sidecar does not run in this topology, so nothing"; \
		     echo "will fetch it for you and the app will report the model missing:"; \
		     echo "   ollama pull $$m"; exit 1; }
	@echo "Using host Ollama at :11434 (no ollama container)."
	OLLAMA_URL=http://host.docker.internal:11434 \
		docker compose --profile ai up --build --no-deps app

# There was no way to bring the stack down. `make stop` frees the port -- and now
# stops the container serving it -- but nothing removed the container and network
# compose creates, so a re-run met a half-existing stack. Both use -t 30 for the
# same reason as every other stop here: shutdown is variable (10.8s settled, over
# 30s during a model load) and both the 10s default and a 30s ceiling SIGKILLed
# healthy shutdowns. -t is a ceiling, not a wait.
docker-stop: require-docker
	@echo "Stopping the Luminary compose stack (containers kept for a fast restart)..."
	@docker compose --profile ai stop -t 90
	@echo "Stopped. 'make docker-down' also removes the containers and network."

# down removes containers and the network. It NEVER takes --volumes: that deletes
# luminary-data, which is the user's library, and no target in this file is
# allowed to do that silently. Do not add it.
docker-down: require-docker
	@echo "Stopping and removing Luminary containers and network..."
	@docker compose --profile ai down -t 90
	@echo "Done. Your library volume is untouched:"
	@docker volume ls --filter name=luminary --format '  {{.Name}}' 2>/dev/null || true

stop:
	@echo "Stopping Luminary on :$(LUMINARY_PORT)..."
	@sh scripts/free_port.sh $(LUMINARY_PORT)

# The frontend typecheck needs `tsc -b`: tsconfig.json is solution-style
# ("files": []), so a bare `tsc --noEmit` resolves zero files and always passes.
lint:
	cd backend && uv run ruff check .
	cd frontend && npx tsc -b --noEmit
	cd frontend && npm run lint
	python3 scripts/check_manifest_schema.py
	python3 scripts/check_manifest_coverage.py
	python3 scripts/check_public_surface_calls.py
	python3 scripts/check_smoke_paths.py
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

# Footprint + interactive-latency baseline. FILE= ingests and samples through it;
# without FILE it samples idle. Backend must be running.
mem-profile:
	@echo "Profiling footprint (requires backend on :7820)..."
	cd backend && uv run python ../scripts/mem_profile.py $(if $(FILE),--ingest $(FILE),) \
		--summary evals/mem_profile_history.jsonl $(MEM_ARGS)

# Compare two GLiNER models on the live corpus before changing NER_MODEL.
# Agreement only -- the deciding gate is `make eval` under each model.
ner-compare:
	@echo "Comparing entity models (requires backend on :7820)..."
	cd backend && uv run python ../scripts/ner_compare.py $(NER_ARGS)

# Intent routing: does the chat graph send each message to the right strategy?
# The graph routes every message by intent, so a misroute makes every downstream
# number describe a question the user did not ask (I-25, I-26). Fast -- no
# generation, just classification.
eval-intent:
	@echo "Intent routing accuracy (backend must be running)..."
	uv run --project $(CURDIR)/backend python evals/run_intent_eval.py --backend-url $(BACKEND_URL) --assert-thresholds
	@echo "Adversarial phrasing, heuristic only -- the floor, and the routing on a slow host..."
	uv run --project $(CURDIR)/backend python evals/run_intent_eval.py \
		--dataset intents_adversarial --backend-url $(BACKEND_URL)
	@echo "Adversarial phrasing, heuristic + LLM fallback -- what a user gets..."
	uv run --project $(CURDIR)/backend python evals/run_intent_eval.py \
		--dataset intents_adversarial --backend-url $(BACKEND_URL) --llm-fallback

# Note search: does /notes/search find the note, and only the note. No golden --
# queries are derived from whatever notes the machine has, so the numbers are
# corpus-coupled and comparable only against your own previous run.
eval-notes:
	@echo "Note search eval (backend must be running)..."
	uv run --project $(CURDIR)/backend python evals/run_note_search_eval.py \
		--backend-url $(BACKEND_URL) --assert-thresholds

# Ingestion fidelity: how much of each source document survives into chunks.
# Deterministic, LLM-free, no backend needed -- it reads the dev database directly.
# Retrieval scores what was indexed and cannot report what never arrived, so this
# is the ceiling every downstream number sits under. Run it before trusting a
# retrieval or generation figure on a corpus that was re-ingested.
# ALL=1 measures every complete document in the library grouped by format --
# epub, docx and scraped articles each reach chunks through a different parse
# path, and the 12 manifest documents cover only txt, md and one PDF.
eval-ingest:
	@echo "Ingestion fidelity across every manifest document..."
	uv run --project $(CURDIR)/backend python evals/run_ingest_eval.py --assert-thresholds \
		$(if $(ALL),--all-documents,)

# Every document kind under DATA. `thoughts` is deliberately absent: 4 rows over a
# 7-chunk document scores 1.000 by construction, so it is measured, not gated.
eval:
	@echo "Running retrieval quality evals (backend must be running on :7820)..."
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset book --backend-url $(BACKEND_URL) --assert-thresholds
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset paper --backend-url $(BACKEND_URL) --assert-thresholds
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset legal --backend-url $(BACKEND_URL) --assert-thresholds
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset play --backend-url $(BACKEND_URL) --assert-thresholds
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset study --backend-url $(BACKEND_URL) --assert-thresholds

# Generation quality on the shipped answering path: faithfulness (HHEM), answer
# relevance, citation support, answer rate and citation coverage -- all asserted.
# Slow: /qa runs sequentially because a local Ollama serves one generation at a
# time. This is the only target that exercises answering; `make eval` is retrieval
# only, which is why every faithfulness column in the UI read "-" before it existed.
eval-gen:
	@echo "Generation quality eval on book + paper (local judge, asserted -- slow)..."
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset book --backend-url $(BACKEND_URL) --judge-model $(EVAL_TEXT_MODEL) --check-citations --assert-thresholds
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset paper --backend-url $(BACKEND_URL) --judge-model $(EVAL_TEXT_MODEL) --check-citations --assert-thresholds

# Repeated generation eval: mean and sd over N runs in ONE library state, gated
# on the mean. A single generation run cannot resolve a change below ~0.10 on
# book or ~0.05 on paper, so this is the only honest way to A/B a change that
# touches answering. RUNS= and COMPARE= (an earlier run_group) are optional.
eval-variance:
	@echo "Repeated generation eval on $(or $(DATASET),book) (slow -- N full runs)..."
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_variance.py \
		--dataset $(or $(DATASET),book) --runs $(or $(RUNS),4) \
		$(if $(COMPARE),--compare-to $(COMPARE),) \
		--backend-url $(BACKEND_URL) --judge-model $(EVAL_TEXT_MODEL) \
		--check-citations --assert-thresholds

# The prompt a task actually sends, and why each part is in it. The PromptSpec
# refactor makes the real prompt exist only at runtime; this is what replaces
# reading the string in the file.
prompt-dump:
	cd backend && uv run python ../scripts/prompt_dump.py \
		--task $(or $(TASK),flashcards) $(if $(MODEL),--model $(MODEL),)

# Which models a run will use, and whether they are installed. Cheap, and the
# only place the one-model / text+vision split is stated before a run rather
# than inferred from a failure.
eval-models:
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python check_models.py \
		--backend-url $(BACKEND_URL) --judge-model $(EVAL_TEXT_MODEL)

# The model matrix: run the model-sensitive evals across candidates and report
# the structural tier, which is the only one allowed to decide a swap. Switches
# the backend's model per candidate and restores it afterwards. ARM=bare needs
# the backend restarted with PROMPT_ARM=bare; the matrix refuses to straddle
# arms. MODELS is required -- there is no default worth guessing.
eval-matrix:
	@echo "Model matrix over $(MODELS) (arm=$(or $(ARM),shipped))..."
	uv run --project $(CURDIR)/backend python evals/run_model_matrix.py \
		--models $(MODELS) --backend-url $(BACKEND_URL) \
		$(if $(TASKS),--tasks $(TASKS),) $(if $(ARM),--arm $(ARM),) \
		$(if $(ASSERT_SEPARATION),--assert-separation,)

# Flashcard quality. SKIP_JUDGE=1 reports the structural half only -- cards
# asked for against cards delivered, and what the parser had to repair. Those
# are deterministic and model-sensitive, which is what gates a model swap; the
# judged scores are neither, and on a one-model machine the judge is grading its
# own cards.
eval-flashcards:
	@echo "Flashcard eval across content kinds..."
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_flashcard_eval.py \
		--backend-url $(BACKEND_URL) --judge-model $(EVAL_TEXT_MODEL) \
		$(if $(SKIP_JUDGE),--skip-judge,) --assert-thresholds

# Rebuild the flashcard golden by sampling passages from the live index. Fixed
# seed, balanced across content types; no model authors anything, because the
# passage is the ground truth the cards are judged against.
golden-flashcards:
	uv run --project $(CURDIR)/backend python evals/build_flashcard_golden.py \
		--per-kind $(or $(PER_KIND),7)

# Cross-document routing: does retrieval pick the right DOCUMENT, unscoped, the
# way real "All documents" chat runs. `make eval` pins each row to its source,
# so it cannot see a routing failure at all. No floor yet -- this records the
# baseline; a threshold needs numbers first, in one library state.
ROUTING_DATASETS ?= book,paper,legal,play,study
eval-routing:
	@echo "Corpus-wide routing (unscoped) on $(ROUTING_DATASETS)..."
	uv run --project $(CURDIR)/backend python evals/run_corpus_routing.py \
		--datasets $(ROUTING_DATASETS) --backend-url $(BACKEND_URL) $(if $(TYPO),--typo,)

# Summary quality. `summary_grounding` (HHEM) needs no LLM; `no_hallucination`
# needs the judge, so SKIP_JUDGE=1 gives the deterministic half on a machine
# with no model to spare.
eval-summary:
	@echo "Summary eval (mode=$(or $(MODE),executive))..."
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_summary_eval.py \
		--mode $(or $(MODE),executive) --backend-url $(BACKEND_URL) \
		--judge-model $(EVAL_TEXT_MODEL) $(if $(SKIP_JUDGE),--skip-judge,) --assert-thresholds

# Everything, in the order the stages constrain each other: ingestion is the
# ceiling on retrieval, retrieval is the ceiling on generation. Running them in
# any other order attributes a regression to the wrong stage.
eval-all:
	$(MAKE) eval-models
	$(MAKE) eval-ingest
	$(MAKE) eval
	$(MAKE) eval-routing
	$(MAKE) eval-gen
	$(MAKE) eval-intent
	$(MAKE) eval-topics

# D2L technical-corpus retrieval (HR@5/MRR). Backend on :7820 with d2l ingested.
# Retrieval-only (--judge-model "" disables the RAGAS judge) so it runs in seconds.
# --no-rerank is explicit: this is the unreranked arm of the A/B below, and the
# harness now defaults to the funnel the app ships (which reranks).
eval-d2l:
	@echo "Retrieval eval on the d2l technical corpus (HR@5/MRR, no judge, no rerank)..."
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset d2l --backend-url $(BACKEND_URL) --judge-model "" --no-rerank --assert-thresholds

# Same dataset WITH the cross-encoder reranker — compare HR@5/MRR against `eval-d2l`.
eval-d2l-rerank:
	@echo "Retrieval eval on d2l WITH cross-encoder reranking (A/B vs eval-d2l)..."
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset d2l --backend-url $(BACKEND_URL) --judge-model "" --rerank

# Generation quality (faithfulness, answer-relevance) via a LOCAL Ollama judge.
# Slow (one judge call per question); separate from the fast HR/MRR target above.
eval-d2l-gen:
	@echo "Generation eval on d2l (RAGAS, local judge — slow)..."
	cd evals && UV_CACHE_DIR=$(CURDIR)/.uv-cache uv run --no-sync python run_eval.py --dataset d2l --backend-url $(BACKEND_URL) --judge-model $(EVAL_TEXT_MODEL)

# Topic-generation eval (precision/recall/F1 + junk-rate). Uses the backend venv.
eval-topics:
	@echo "Topic-generation eval on d2l..."
	uv run --project $(CURDIR)/backend python evals/run_topic_eval.py --dataset d2l --backend-url $(BACKEND_URL) --assert-thresholds

# Regenerate the d2l golden Q&A (ONE-TIME, needs OPENAI_API_KEY + Ollama). Overwrites d2l.jsonl.
golden-d2l:
	@echo "Regenerating d2l golden (GPT-5.4 generate + cross-model verify)..."
	LUMINARY_ENV_FILE=$(CURDIR)/backend/.env uv run --project $(CURDIR)/backend python evals/generate_golden.py \
		--source DATA/books/d2l_dive_into_deep_learning.md \
		--out evals/golden/d2l.jsonl \
		--generator-model openai/gpt-5.4 \
		--verify-models openai/gpt-5.1 ollama/qwen2.5:14b-instruct \
		--verify-axes answerable answer_correct --target 50

# Regenerate the paper golden Q&A (ONE-TIME, needs OPENAI_API_KEY + Ollama). Overwrites
# paper.jsonl. The source is a site scrape, so the generator reads it through
# source_text.read_source_text -- the same furniture removal ingestion applies. Reading it
# raw is how 17 of the previous 40 questions came to ask about the site's 404 page.
golden-paper:
	@echo "Regenerating paper golden (GPT-5.4 generate + cross-model verify)..."
	LUMINARY_ENV_FILE=$(CURDIR)/backend/.env uv run --project $(CURDIR)/backend python evals/generate_golden.py \
		--source DATA/papers/art_of_unix.txt \
		--out evals/golden/paper.jsonl \
		--generator-model openai/gpt-5.4 \
		--verify-models openai/gpt-5.1 ollama/qwen2.5:14b-instruct \
		--verify-axes answerable answer_correct --target 40

# Goldens for the document kinds that had none. `study` is the only PDF dataset,
# so it is the only thing measuring the PDF parse path.
golden-legal:
	@echo "Regenerating legal golden (GPT-5.4 generate + cross-model verify)..."
	LUMINARY_ENV_FILE=$(CURDIR)/backend/.env uv run --project $(CURDIR)/backend python evals/generate_golden.py \
		--source DATA/legal/federalist_papers.txt \
		--out evals/golden/legal.jsonl \
		--generator-model openai/gpt-5.4 \
		--verify-models openai/gpt-5.1 ollama/qwen2.5:14b-instruct \
		--verify-axes answerable answer_correct --target 60

golden-play:
	@echo "Regenerating play golden (GPT-5.4 generate + cross-model verify)..."
	LUMINARY_ENV_FILE=$(CURDIR)/backend/.env uv run --project $(CURDIR)/backend python evals/generate_golden.py \
		--source DATA/plays/hamlet.txt \
		--out evals/golden/play.jsonl \
		--generator-model openai/gpt-5.4 \
		--verify-models openai/gpt-5.1 ollama/qwen2.5:14b-instruct \
		--verify-axes answerable answer_correct --target 60

golden-study:
	@echo "Regenerating study golden (GPT-5.4 generate + cross-model verify)..."
	LUMINARY_ENV_FILE=$(CURDIR)/backend/.env uv run --project $(CURDIR)/backend python evals/generate_golden.py \
		--source DATA/study/sutton_barto_rl.pdf \
		--out evals/golden/study.jsonl \
		--generator-model openai/gpt-5.4 \
		--verify-models openai/gpt-5.1 ollama/qwen2.5:14b-instruct \
		--verify-axes answerable answer_correct --target 60

golden-thoughts:
	@echo "Regenerating thoughts golden (GPT-5.4 generate + cross-model verify)..."
	LUMINARY_ENV_FILE=$(CURDIR)/backend/.env uv run --project $(CURDIR)/backend python evals/generate_golden.py \
		--source DATA/daily_thoughts_2026.txt \
		--out evals/golden/thoughts.jsonl \
		--generator-model openai/gpt-5.4 \
		--verify-models openai/gpt-5.1 ollama/qwen2.5:14b-instruct \
		--verify-axes answerable answer_correct --target 20

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
	@$(MAKE) --no-print-directory require-docker
	docker build -q -t luminary-ci -f backend/Dockerfile.ci .
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
	python3 scripts/check_public_surface_calls.py
	python3 scripts/check_smoke_paths.py
	bash scripts/check_powershell.sh
	cd frontend && npm run build
	python3 scripts/check_public_bundle_excludes_full.py
	cd frontend && npx tsc -b --noEmit
	cd frontend && npm run lint
	# The frontend suite was never wired into a gate: 59 files of pure-logic
	# tests ran only when someone typed `npm test`, so a broken helper reached
	# master green. It costs ~1s.
	cd frontend && npm test
	cd frontend && npm test
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
