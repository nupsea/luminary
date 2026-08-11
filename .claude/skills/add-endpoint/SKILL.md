---
name: add-endpoint
description: The end-to-end shape of adding or changing a backend HTTP endpoint in this repo — schema, repo, service, router, test, generated types, smoke script, surface manifest. Use whenever adding a route, changing a response shape, or wiring a new router into the app.
---

# Adding an endpoint

The steps are spread across `docs/patterns.md`, the PR template and two manifest checkers. This
is the whole sequence. Skipping the last three is the usual way a change passes `make ci` and
still breaks the app.

## Layers, in order

Follow `Types → Config → Repo → Service → Runtime → API`. Never import backwards;
`layer_linter.py` fails CI on it, and its `KNOWN_VIOLATIONS` set may only shrink.

1. **Schema** — `backend/app/schemas/<domain>.py`. Pydantic request/response models. Zero I/O,
   no imports from other layers.

2. **Repo** — `backend/app/repos/`. Data access only: SQLAlchemy queries, LanceDB, Kuzu Cypher.
   No business logic. Use `repos/_helpers.get_or_404`, which raises `NotFound`.
   - Wrap every synchronous LanceDB and Kuzu call in `asyncio.to_thread` (I-2). One worker
     serves every request, so a blocking call stalls the entire app, not just this route.
   - Never share an `AsyncSession` across `asyncio.gather` tasks (I-1).

3. **Service** — `backend/app/services/<domain>.py`. Business logic.
   - **Raise `LuminaryError` subclasses, never `HTTPException`.** `main.py` registers one handler
     that maps `status_code` and spreads `extra` into the body. `NotFound`, `Conflict`,
     `InvalidInput` and `DependencyUnavailable` cover most cases; a domain hierarchy subclasses
     `LuminaryError` and sets `status_code` per leaf.
   - All LLM calls go through LiteLLM, never a provider SDK.

4. **Router** — `backend/app/routers/<domain>.py`. Thin: validate, call service, return.
   - **Register literal segments before parametric ones.** `/resource/active` must be declared
     above `/resource/{id}`, or the router matches `active` as an id. This is the single most
     common routing bug in this codebase.
   - HTTP 204 uses `Response(status_code=204)` directly — FastAPI cannot serialize a `None` body
     through `response_model`.
   - Validate any request value that gets spread into a subprocess argv. A list-valued option
     after `nargs="*"` lets a value starting with `-` be re-parsed as a flag by the child, which
     is an arbitrary file read/write primitive even without `shell=True`.
   - New router file? Register it in `main.py`.

5. **Test** — `backend/tests/`, mirroring `app/`. At least one pytest test per endpoint; this is
   a stated PR requirement. In-memory pattern: `make_engine("sqlite+aiosqlite:///:memory:")` +
   `create_all_tables()`, monkeypatching `db_module._engine` and `db_module._session_factory`.

## The three steps people skip

6. **Regenerate types:** `make regen-api-types`. The frontend reads
   `frontend/src/types/api.ts`, which is generated from the OpenAPI schema. Never edit it and
   never open it — 18k lines. Grep it for a type name.

7. **Smoke script:** add `scripts/smoke/S<next>.sh` and wire it into `scripts/smoke/all.sh`.
   Numbering is sequential — check the highest existing number, do not guess. Copy the shape of
   a neighbouring script: `set -euo pipefail`, health check against `:7820` first, then assert
   the status code and body shape, `echo "PASS: S### -- ..."`.

   This is the only check that runs against a live server. `pytest` runs the app in-process and
   cannot catch a mis-ordered route or a response the UI reads differently (I-14).

8. **Surface manifest:** `check_manifest_coverage.py` asserts that every router in
   `backend/app/routers/` is either named in a `surface-manifest.json` entry's
   `backend.routers` or on the explicit allow-list. A new router with no entry fails `make lint`.
   Pick a `mode` (`full` or `public`) deliberately — `public` is the curated learner set that
   ships in installers. `backend/app/surface_manifest.py` and
   `frontend/src/lib/surfaceManifest.ts` must stay mirrored.

## Verify

`make ci`, then `make smoke` with a backend running on :7820. Both, not either.
