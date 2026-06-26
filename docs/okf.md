---
description: OKF (Open Knowledge Format) -- the portable knowledge projection layer. NOT a model connector (that's LiteLLM). Read before any export/grounding/import or blog-publish work.
---

# OKF -- portable knowledge, model-agnostic grounding

**One-line truth:** OKF is *not* a model connector -- LiteLLM already connects Lumen to Ollama /
OpenAI / Anthropic / Gemini. OKF is the **portable knowledge layer**: a folder of Markdown files
with YAML front-matter (one file per [concept](concepts.md), links form the graph, plus `index.md`
+ `log.md`). It sits **on top of** the live stores as an interchange + export + grounding-context
layer -- never a replacement for SQLite/LanceDB/Kuzu, and never a transport.

```
LiteLLM = the WIRE   (how bytes reach any vendor)    -- already shipped
OKF     = the PAYLOAD (what knowledge grounds the model, as portable files) -- net-new (Phase 5)
They compose: LiteLLM is HOW you talk to the model; OKF is WHAT you say.
```

This separation is **constitution rule 13** and **invariant**: transport and knowledge never
couple; knowledge is never locked into a store the user can't read.

## OKF is a derived projection, not a source of truth

Truth lives in SQLite (state) + Kuzu (topology) -- see
[concepts.md](concepts.md#representation----two-truths-two-derived-projections). OKF files are
**regenerated** from those. The only way a file edit re-enters the system is as an `override`
(constitution rule 8: "the learner model is files the user can read, edit, delete"; user edits are
treated like graph overrides and re-apply after re-parse). This keeps sync one-directional and
avoids three-way conflict on the hot review path.

## Bundle layout

```
.luminary/okf/
|- index.md                 # entry: goals, what this bundle covers
|- log.md                   # chronological learning history (append-only)
|- concepts/
|  |- iceberg-manifests.md  # frontmatter: type, title, mastery, recency, evidence[], links[]
|- learner/
|  |- profile.md            # stable traits (the "skill.md") -- user-editable
|  |- memory.md             # rolling episodic digest
|  |- misconceptions.md
|- sources/                 # citations back to the user's documents
```

One concept file per Kuzu concept node; front-matter from the SQLite state + FSRS; body = evidence
quotes + Markdown links to neighbour concepts (the Kuzu edges). Notes are already Markdown ->
near-passthrough. The concept's stable `slug` (see schema) is the filename.

## Three integration points (build in this order -- Phase 5)

### 1. Export (start here -- replaces the Obsidian-vault export)

Project the live stores into an OKF bundle on disk -- the local-first promise made literal.

- New `services/okf_exporter.py` + `POST /okf/export` (new `okf` router, **public** tier).
- Reframe the labs **blog publish** as "export/share an OKF bundle" (same plumbing, broader value).
- **D6:** keep both the Markdown-vault export and OKF for one release (deprecation window), then
  hard-switch.

### 2. Grounding-context (the real "switch vendors" answer)

When Lumen assembles context for **any** LiteLLM call, build it as an **OKF projection** of the
relevant concepts + evidence + learner notes. Then Private->Hybrid->Cloud changes only the wire;
the same plain-text bundle grounds a local 3B Llama and cloud Claude **identically**.

- New `services/okf_context.py`: `scope -> OKF context string`, used by the QA + assembler prompts.
- Strictly local assembly; honors **I-16/I-17/I-18** (no content to telemetry; cloud is per-feature
  opt-in).

### 3. Import (two-way sharing)

A bundle is shareable: import someone's "Lakehouse design" pack and study it.

- `services/okf_importer.py` + `POST /okf/import`: read bundle -> upsert concepts/edges as
  **proposed** -> user reviews via the same "what Lumen found" surface used at ingest.
- Imported concepts start as **`candidate`** (origin `import`) until a local doc covers them or the
  user confirms -- keeps the grounded graph honest.

## What OKF does NOT change

- Model connectivity (LiteLLM owns it; vendor config stays in `backend/.env`).
- The fast operational path (SQLite/LanceDB/Kuzu stay; OKF is a projection, not the primary store).

## Done-bar

- `POST /okf/export` produces a valid bundle that round-trips through `POST /okf/import`.
- A QA answer grounded via `okf_context` is identical in **knowledge** across Ollama and a cloud
  model (only latency/quality differ).
- Imported concepts land as proposed/candidate and are correctable.
