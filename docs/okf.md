---
description: OKF (Open Knowledge Format) -- the portable knowledge projection layer. NOT a model connector (that's LiteLLM). Design doc; only the grounding half is built. Read before any export/grounding/import or blog-publish work.
---

# OKF -- model-agnostic grounding

**What exists is a grounding assembler, and this file describes only that.** The Markdown file
projection this name originally referred to -- one file per concept, `index.md`, `log.md`, export
and import -- is not built. It is tracked as an open item in [roadmap.md](roadmap.md), and I-21
governs it if it is ever built. Nothing about files is callable today.

## The grounding assembler

`services/okf_context.py` turns a scope into a plain-text grounding block, and `routers/qa.py`
consumes it. Two entry points:

- **`resolve_concepts`** -- scope to concept ids. A concept expands to itself plus its
  neighbours; a free-text query resolves lexically rather than by vector, because concept
  centroids live in the 384-dim chunk space and not the query space.
- **`build_concept_context`** -- per concept, its evidence quotes and related concepts,
  assembled into one block.

## Why it is worth having a name

The block is plain text, assembled locally, and identical whichever model receives it. That is
the whole point: moving between a local model and a cloud one changes the wire, not the
grounding. It also keeps I-16/I-17/I-18 honest -- no document content reaches telemetry, and
cloud use stays per-feature opt-in -- because there is one place where context is built and it
is local.

## What it does not do

It is derived, never a source of truth. SQLite, LanceDB and Kuzu hold the state; this assembles
a view of it for a prompt. Nothing reads it back, and losing it costs nothing but a rebuild.
