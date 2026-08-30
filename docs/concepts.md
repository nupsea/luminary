---
description: The Concept primitive -- the single studyable atom. The canonical answer to "what is a concept" and how it differs from a Kuzu Entity. Read before any concept/mastery/graph work.
---

# Concepts -- the studyable atom

This is the canonical answer to **"what is a concept?"** A Concept is the one thing Luminary lets
you *study* and the only thing that carries mastery. Everything else is either material that
*produces* concepts (documents, notes) or scope that *selects* them (collections, tags).

## Entity vs Concept (the fundamental distinction)

Today the Kuzu graph stores **`Entity`** nodes (GLiNER zero-shot NER). An Entity and a Concept are
**not** the same thing -- conflating them is the central mistake this design avoids.

| | **Entity** (exists today, Kuzu) | **Concept** (net-new) |
|---|---|---|
| What it is | a *mention* -- a lexical NER surface-form | *something you can master* -- a pedagogical unit |
| Identity | the string label; many entities per real idea | a stable `id`; deduplicated across mentions/aliases |
| Source | GLiNER over chunk text | promoted from a cluster of related Entities (or proposed from notes/quiz/chat/import) |
| Learning state | none | mastery, stability, last_reviewed (FSRS-derived) |
| Trust metadata | none | `origin`, `status`, `evidence[]` |
| Role | raw co-occurrence material | the routing unit for sessions, gaps, and study |

**Entities are raw material; Concepts are the curated, studyable layer above them.** A Concept is
minted by *promoting* an Entity cluster (see [lifecycle](#lifecycle)) -- it is never just a renamed
Entity. The Kuzu `(:Concept)-[:PROMOTED_FROM]->(:Entity)` edge preserves that provenance.

> Why this matters in practice: mastery used to be faked by `chunk.text ILIKE '%name%'`
> (`mastery_service.py`, `study_path_service.py`) -- a string match against an Entity label. That
> is ephemeral and lexical. A Concept makes mastery a **stored, stable scalar** you can route on.

## Representation -- two truths, two derived projections

The same Concept is represented across four stores. **Two are source of truth; two are derived**
(regenerated from the truths -- so there is never a sync conflict on the hot review path).

| Store | Owns | Truth? | Invariants |
|---|---|---|---|
| **SQLite** `concepts` | hot, mutable state -- see schema below; `flashcards.concept_id` | **yes** | I-1 (no shared AsyncSession across `gather`) |
| **Kuzu** `(:Concept {id})` | topology -- node + concept-concept edges, routes, prereqs, provenance edges | **yes** | I-3 (`has_next()` before `get_next()`) |
| **LanceDB** `concept_vectors_v1` | 384-dim vector (chunk/bge-small space) for similarity/linking/dedup | derived | I-2 (`to_thread`), I-20 |
| **OKF** `okf/concepts/<slug>.md` | portable text projection (frontmatter + evidence + links) | derived (Phase 5) | edits flow back only as `overrides`; never a transport |

### SQLite schema (source of truth for state)

```
concepts(
  id            TEXT PRIMARY KEY,         -- stable id
  slug          TEXT UNIQUE,              -- human-readable, OKF filename; stable across renames
  label         TEXT,                     -- display name (user-correctable via override)
  kind          TEXT,                     -- 'concept' | 'keyword'  (keyword = weaker claim)
  origin        TEXT DEFAULT 'document',  -- document | note | quiz | chat | import
  status        TEXT DEFAULT 'confirmed', -- candidate | proposed | confirmed
  mastery       REAL DEFAULT 0,           -- 0..100, stored scalar (NOT recomputed by text match)
  stability     REAL DEFAULT 0,           -- FSRS stability (days)
  last_reviewed TIMESTAMP NULL,           -- 0/NULL = never studied
  evidence_json TEXT                      -- [{document_id, chunk_id, quote}] -- the trust receipt
)
```

`flashcards` gains: `concept_id` (**nullable** -- unmapped cards), `source_scope` (text),
`mapping_status` (`mapped | unmapped | proposed`). See
[two-lane-model.md](two-lane-model.md#unmapped-cards).

### Kuzu topology (source of truth for the graph)

```
(:Concept {id, slug, label, kind, status})
(:Concept)-[:CONCEPT_RELATED_TO {weight, status}]->(:Concept)   -- inferred; status proposed|confirmed|rejected
(:Concept)-[:CONCEPT_PREREQUISITE_OF {confidence}]->(:Concept)  -- ordering for routes
(:Concept)-[:EXTRACTED_FROM]->(:Document)                       -- availability / provenance
(:Concept)-[:PROMOTED_FROM {confidence}]->(:Entity)             -- bridge to the NER layer
```

> Storage note: the concept-concept edges use `CONCEPT_`-prefixed names because Kuzu rel
> tables are typed by their endpoint pair and the Entity-level `RELATED_TO` / `PREREQUISITE_OF`
> tables already exist. Conceptually they are the same "related"/"prerequisite" relations.

The existing `WRITTEN_ABOUT (Note -> Entity)` engagement edges are reachable through
`PROMOTED_FROM`, so "N notes touch this concept" is a graph query, not a new store.

### LanceDB vector (derived -- for similarity, not retrieval)

A concept's vector = **centroid of its evidence-chunk embeddings** (the chunks already live in
LanceDB; this is a free vector mean, recomputed when evidence changes on re-parse). Chunks are
embedded with **bge-small-en-v1.5 (384-dim)**, so concept vectors live in that same **384-dim chunk
space** -- directly comparable to chunks and to bge-small query embeddings. A future upgrade
synthesizes `label + gloss + top evidence` and re-embeds it with the same chunk embedder for higher
quality (staying in one space). Notes are embedded with the same bge-small chunk embedder, so
note->concept matching compares directly in that shared space (falling back to title/lexical when a
note has no vector yet).

Used for: Entity->Concept dedup, note->concept link chips (degraded path), candidate-concept
seeding, scope->concept resolution. **Never** a retrieval primary -- chunk vectors + FTS5 + graph
(RRF) stay the RAG backbone.

### OKF projection (derived -- Phase 5)

One Markdown file per concept: front-matter from the SQLite state, body = evidence quotes, links =
Kuzu edges. See [concepts.md](concepts.md). The file is **not** the truth; a user edit becomes an `override`
that re-applies after re-parse -- the same channel as a graph rename/merge.

## Lifecycle

```
                      Lane A (document-driven, automatic)
 Entities (NER) --cluster--> promote --> Concept(origin=document, status=proposed)
                                              | confirm OR use in a Study Event
                                              v
                                         status=solid/confirmed

                      Lane B (user material leads)
 note / quiz cluster / chat / OKF import --> Concept(origin=note|..., status=candidate)
                                              | a document later covers it OR user confirms
                                              v
                                         joins the grounded graph (gap/route eligible)
```

- **proposed**: a fresh extraction. Renders lighter. Confirming it -- or using it in a session --
  promotes it to **solid/confirmed**. Trust accrues through use.
- **candidate**: proposed from non-document material. Dimmer star; **excluded from gap/route
  participation** until grounded. Keeps the doc-grounded graph honest.
- **keyword vs concept**: when unsure, the model proposes a `keyword` (weak claim), not a
  `concept` (strong claim), and routes low-confidence items to the optional review pass.

**Under-claim over mislabel.** A missed concept is recoverable; a confidently wrong one erodes the
product's credibility.

## Mastery

Mastery is a **stored scalar on the concept row**, written by the assessment pipeline (Study
Events) -- never recomputed by text match, never on documents or collections.

```
mastery(concept) = fsrs_retrievability(concept's cards)        # backbone, always available
                   blended with calibration accuracy            # metacognition signal
IF Feynman available (full mode) AND a teach-back exists:
   teach-back coverage RAISES the attainable ceiling            # generation certifies
ELSE:
   no artificial cap -- FSRS + calibration stand on their own   # the old "cap at 80" is REMOVED
warmth(concept)  = clamp(1 - daysSince(last_reviewed)/18, 0..1) # decay signal for warm-ups
```

Rollups are **computed, never stored as truth**:

```
collectionMastery(c) = aggregate(mastery for concepts lit by c's documents)
```

A collection's mastery moves *automatically* after a session because the session wrote back to the
concepts -- there is no separate "study a collection" engine.

## Corrections survive re-parse (overrides)

Documents are read-only, but every Lumen guess is correctable. Each correction writes an
`Override` keyed by stable concept/edge identity:

- **Concept**: rename · merge ("same as...") · split ("actually two things") · reject ("not a
  concept") · reclassify concept<->keyword · add a missed concept · promote a highlight.
- **Edge**: confirm · reject (rejected edges never re-appear).
- **Gap**: accept (-> "add a source") · dismiss ("not relevant" -- hidden, not deleted).

Re-parse produces fresh proposals, then `applyOverrides()` re-applies every user decision on top.
**A rejected/edited element must not reappear after re-parse.** Overrides are the user's permanent
voice over Lumen's guesses; OKF file edits feed this same channel.

## Acceptance checks (for any concept work)

- [ ] Adding a document produces concept nodes with visible `evidence` passages.
- [ ] Concepts extract from **documents**; notes/quiz/chat/import create **candidate** concepts;
      sessions only update mastery -- none silently mints a confirmed node.
- [ ] Mastery exists only on concepts; collection numbers are computed rollups.
- [ ] A concept shared by two collections appears once, belonging to both.
- [ ] Rejecting a concept/edge or dismissing a gap never reappears after re-parse.
- [ ] Every concept exposes `evidence` -- the trust receipt.

---

## How a concept is built (the extraction pipeline)


This documents **how concepts are extracted** from a library. For the **what/why of the Concept
primitive** (mastery, lifecycle, the studyable atom) read [concepts.md](concepts.md) first. The old
strict-tree hierarchy, forced clustering, and the LangGraph framing in earlier versions of this doc
are **superseded**; what remains below is the still-true pipeline craft.

The concept layer is the spine that connects abstract material down to generatable text and up to
mastery. If a piece of data isn't needed by a downstream use case, we don't store it.

### Pipeline shape (built)

A **plain sequential runner** (`app/workflows/concept_pipeline.py`), not LangGraph -- a StateGraph
dropped the `hierarchy` key, so the pipeline is explicit and ordered. Each stage is an independent,
swappable node in `app/workflows/concept_nodes/`, inspectable via `make concepts-dryrun`:

```
select_entities -> embed_entities -> build_hierarchy -> label_levels -> score_concepts -> persist_concepts
```

Tunable knobs live in `concept_nodes/_shared.py::PIPELINE_CONFIG`.

### 1. Entity selection -- relevance starts here

Not every NER entity is a concept seed. GLiNER emits PERSON, ORGANIZATION, LOCATION, DATE, etc.
(`ner.py ENTITY_TYPES`) -- those produce noise.

- **Keep** concept-bearing types (CONCEPT, METHOD, DATA_STRUCTURE, ALGORITHM, TECHNOLOGY, domain
  nouns); **drop** PERSON / ORGANIZATION / LOCATION / DATE / misc by default (configurable per corpus
  -- a history library may want PERSON).
- **Frequency floor** + `is_junk_entity` (numbers / latex / formula / unicode-styled garbage /
  CLI flags / snake_case code identifiers / source literals / generic-stopword filter).
- This filter is deterministic and is the single biggest relevance lever (**lever 1**).
- **Lever 2 -- studyability gate (`score_concepts`).** Format filtering cannot judge whether a
  real word is worth studying. After labelling, an LLM flags low-quality level-2 concepts
  (too generic, placeholder/example names, instructions) and `persist` writes them as
  `status="candidate"` -- kept in the graph but excluded from grounding and the study view.
  Fail-open: a model error leaves every concept `proposed`. Retroactive cleanup of format-junk
  on an existing library: `POST /concepts/purge-junk` (`dry_run=true` previews; `dry_run=false`
  deletes from all three stores).

### 2. Embeddings -- context, not bare names

Cluster on **context embeddings**, not the entity string. Each entity's vector = centroid of the
**chunk** vectors where it occurs (bge-small, 384-dim; matched via `chunk.entities_text`, capped per
entity; `vector_store.fetch_chunk_vectors` bulk load). "Transformer" in an ML book vs an electrical
text then separate correctly. Name-embedding fallback; degrades if no DB. (This fixed the "bloom
filter" clustering.)

### 3. Clustering -- emergent, not a forced count

One average-linkage cosine dendrogram (`scipy.cluster.hierarchy.linkage(method='average',
metric='cosine')`); cut **once** into concepts via `fcluster maxclust` (gap/percentile cuts were
pathological on bge-small). The **number of concepts is an outcome of the data, never a forced
`n_clusters`**. Edges are k-NN (top-k above a cosine cutoff), **not** all-pairs (all-pairs exploded to
a 75k-edge hairball). The sun/medoid of a cluster = its most-central member.

> **Flat layer (2026-06-24).** The upper hierarchy tiers were removed -- nothing read them.
> `build_hierarchy` now emits a single concept level + RELATED_TO edges; `label_levels` labels
> concepts by their sun (no LLM);
> `persist` writes level-2 concepts with no parent chain. A `verify`/dedup node (merge near-duplicates
> by centroid; under-claim over mislabel) still lands before persist.

### 4. Model-routed LLM labelling

The LLM works in stages, model matched to the job (LiteLLM routing), all **offline/idle and
throttled** (semaphore + paced), never on the live loop:

| Step | Job | Tool / model |
|---|---|---|
| cluster | group entities | embeddings + co-occurrence (no LLM) |
| label leaf | name a tight cluster | heuristic medoid, or a small/fast model |
| abstract | name higher tiers + write summaries | a stronger reasoning model, given labels + sample evidence |
| verify | coherence check, merge near-dupes, reject incoherent | reasoning model, batched |

The model proposes; nothing is asserted as fact. Low-confidence groupings become
`proposed`/`candidate`, not `confirmed`. **Under-claim over mislabel** -- a missed concept is
recoverable; a confidently wrong one erodes credibility.

### 5. Stable identity -- so re-extraction doesn't reset the user

A concept's **slug derives from its lineage signature** (a hash over its sorted member-entity set),
**not** from the volatile LLM label. Consequences:

- The same cluster keeps the **same slug** across regenerations -> user overrides (rename/merge/reject)
  and mastery persist (re-applied/keyed by slug, I-22).
- A label change ("Data Systems" -> "Data Engineering") is a relabel of the same identity, not a new
  concept.

This is what makes `make concepts` safe to run repeatedly (manual + idle/background).

### 6. Persisted lineage -- the bridge to material

The abstraction lineage is persisted, not thrown away -- it is the single source for generation
material, mastery, evidence receipts, and doc-overview membership:

- `concepts.parent_id` (SQLite) is unused in the flat layer; membership truth is Kuzu edges (I-23).
- `(:Concept)-[:PROMOTED_FROM]->(:Entity)` -- which entities make up a concept.
- `(:Concept)-[:EXTRACTED_FROM]->(:Document)` -- availability/provenance.
- entity->chunk occurrence index (from `chunk.entities_text`) -- resolves a concept to its passages
  for generation and evidence; `evidence_json = {chunk_ids, document_ids, members}`.

### 7. Observability -- every stage is inspectable

Verification must not require reading code. Each node logs structured, human-readable progress (counts
in/out, what was kept vs dropped and *why*, cluster sizes + cohesion, cluster->label with the model
used, lineage fan-out, persisted slug + identity hash) and accumulates a `diagnostics` block.

`make concepts` supports:
- `--dry-run` -- run every node except `persist`; dump the full diagnostics report. The relevance-tuning
  loop: judge the output on real data before touching the DB.
- `--verbose` -- per-node detail to stdout.
- a written report at `.luminary/concepts/last_run.json`.

Principle: if a grouping looks wrong, the logs must show *why* -- which entities fed it, which step
grouped them, what score let it through.

### 8. Known perf gotchas

- Full-text entity->chunk matching OOM-killed `make concepts` (exit 143) -> use the short
  `entities_text`, not full chunk text.
- All-pairs concept edges exploded persist + produced a hairball -> k-NN with a cutoff.
- Never run heavy concept work in the live server lifespan -- sync Kuzu starves the event loop.
  Offline `make concepts`, with the server stopped, is the only supported path.

---

## Grounding: turning concepts into prompt context


**What exists is a grounding assembler, and this file describes only that.** The Markdown file
projection this name originally referred to -- one file per concept, `index.md`, `log.md`, export
and import -- is not built. It is tracked as an open item in [roadmap.md](roadmap.md), and I-21
governs it if it is ever built. Nothing about files is callable today.

### The grounding assembler

`services/okf_context.py` turns a scope into a plain-text grounding block, and `routers/qa.py`
consumes it. Two entry points:

- **`resolve_concepts`** -- scope to concept ids. A concept expands to itself plus its
  neighbours; a free-text query resolves lexically rather than by vector, because concept
  centroids live in the 384-dim chunk space and not the query space.
- **`build_concept_context`** -- per concept, its evidence quotes and related concepts,
  assembled into one block.

### Why it is worth having a name

The block is plain text, assembled locally, and identical whichever model receives it. That is
the whole point: moving between a local model and a cloud one changes the wire, not the
grounding. It also keeps I-16/I-17/I-18 honest -- no document content reaches telemetry, and
cloud use stays per-feature opt-in -- because there is one place where context is built and it
is local.

### What it does not do

It is derived, never a source of truth. SQLite, LanceDB and Kuzu hold the state; this assembles
a view of it for a prompt. Nothing reads it back, and losing it costs nothing but a rebuild.
