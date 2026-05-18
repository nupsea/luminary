# Generated API types

`api.ts` is auto-generated from the FastAPI OpenAPI schema.
**Do not edit it by hand.** The file ships with the repo so contributors
can build immediately after `npm install` -- regenerate it whenever
the backend contract changes.

## When to regenerate

Run the regen command after any of:

- adding / removing / renaming a Pydantic schema field
  (`backend/app/schemas/*.py` or `backend/app/models.py`)
- changing a route signature, path, query/body shape, or
  `response_model` (`backend/app/routers/*.py`)
- bumping `openapi-typescript` to a new major in
  `frontend/package.json`

There is no auto-regen on `npm run dev` -- the dump requires booting
the FastAPI module, which loads transformers/torch and is too slow
for the inner loop. Treat it like a database migration: run it once
when the contract changes, commit the regenerated file with the
contract change.

## How to regenerate

From the repo root:

```sh
make regen-api-types        # or
cd frontend && npm run regen:api-types
```

Both invoke `frontend/scripts/regen-api-types.sh`, which:

1. runs `uv run python -m tools.dump_openapi` in `backend/` to write
   the OpenAPI 3.x schema to a tmp file,
2. feeds the schema to `npx openapi-typescript` (locally installed
   devDep, version-pinned in `package.json`),
3. writes `frontend/src/types/api.ts`.

## How to use

```ts
import type { components } from "@/types/api";

type FlashcardResponse = components["schemas"]["FlashcardResponse"];
```

Conventions:

- **Always import via `components["schemas"][...]`.** Don't re-export
  schemas under shorter aliases at the top level of `api.ts` -- the
  file is regenerated and any handwritten aliases get clobbered.
- **Define short aliases in feature modules**, e.g.
  `lib/flashcardsApi.ts` can do `export type FlashcardResponse =
  components["schemas"]["FlashcardResponse"];`. That keeps consumer
  code terse without polluting the generated file.
- For inputs (request bodies), use `components["schemas"][...]` too;
  for path/query params use `paths["/route"]["get"]["parameters"]`.

## Why this exists

Before this generator landed, ~6+ components re-declared `type
FlashcardResponse = { id: string; ... }` inline. When the backend
schema changed, the frontend silently drifted. Generating the types
makes drift a TypeScript compile error.
