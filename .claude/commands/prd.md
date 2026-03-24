---
name: prd
description: Generate a Product Requirements Document for a new Luminary feature. Use when planning a new phase or significant feature set. Triggers on: create a prd, write prd for, plan this feature, requirements for, spec out.
user-invocable: true
---

# PRD Generator for Luminary

Creates a structured PRD for a new Luminary feature, then optionally converts it to stories in `scripts/ralph/prd-v3.json`.

## Step 1: Clarifying Questions

Ask 3-5 critical questions where the feature description is ambiguous. Use lettered options so the user can reply with "1A, 2C, 3B":

```
1. Which tab(s) does this feature affect?
   A. Notes tab only
   B. Viz tab only
   C. Notes + Viz (cross-tab)
   D. New tab
   E. Backend only (no UI)

2. What is the data scope?
   A. Per-note (affects individual notes)
   B. Per-collection (affects groups of notes)
   C. Cross-document (spans books and notes)
   D. Global (affects the entire library)

3. Does this require new ML models or external services?
   A. No -- uses existing bge-m3, GLiNER, LiteLLM
   B. Yes -- new model needed (specify)
   C. Yes -- new external API needed (specify)
```

Only ask questions whose answers would change the story decomposition.

## Step 2: PRD Structure

```markdown
# PRD: <Feature Name>

**Phase:** V3 Phase <n> -- <Phase Name>
**Status:** draft

## Introduction

<2-3 sentences: what the feature does and why it matters for a local knowledge assistant>

## Goals

- <Specific, measurable objective>
- <...>

## User Stories

### S<n>: <Title>
**Description:** CONTEXT: <current state> USER JOURNEY: <User does X in [Tab] -> sees Y>
**Acceptance Criteria:**
- <verifiable criterion>
- npx tsc --noEmit exits 0; uv run ruff check . exits 0; uv run pytest exits 0
- scripts/smoke/S<n>.sh exits 0

(repeat for each story)

## Functional Requirements

- FR-1: <explicit requirement>
- FR-2: <...>

## Non-Goals

- <What this feature will NOT do>

## Technical Constraints

- Stack: Python 3.13 + FastAPI (backend), React 18 + TypeScript 5 + shadcn/ui (frontend)
- No new packages without justification -- prefer extending existing ones (uv add only)
- All async DB calls: SQLAlchemy AsyncSession, never share session across asyncio.gather
- All Kuzu get_next() calls must be guarded by has_next()
- LanceDB sync calls in async context must use asyncio.to_thread()
- Six-layer import rule: Types -> Config -> Repo -> Service -> Runtime -> API (no reverse imports)

## Story Dependency Order

<List stories in dependency order: schema/models before services, services before UI>

## Success Metrics

- <How to verify the feature works at scale>
- p95 query latency < Xms at Y notes/documents
```

## Step 3: Convert to PRD JSON (Optional)

After writing the PRD markdown, ask:
> "Save these stories to prd-v3.json? (yes/no)"

If yes, append each story to `scripts/ralph/prd-v3.json` following the Luminary story format.

## Story Sizing for Luminary

The Luminary backend has clear seams for right-sizing:
- **Schema story**: models.py + db_init.py + migration only
- **Service story**: one service class with its repo calls and ML model invocations
- **Router story**: endpoints that call an existing service (thin handlers)
- **UI story**: one component tree or one page section
- **Integration story**: wiring together a backend feature and its UI counterpart

Never combine schema + service + UI in one story. Each layer is a separate story.
