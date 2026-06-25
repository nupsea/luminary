---
description: Concept extraction PIPELINE -- implementation reference (entity selection, context embeddings, model-routed labelling, stable identity, observability). For the knowledge MODEL (goals, graph substrate, mastery, the Universe), read knowledge-model.md, which supersedes this doc's old model/plan sections.
---

# Concept extraction pipeline -- implementation reference

This documents **how concepts are extracted** from a library. The **what/why of the knowledge model**
(goal layer, poly graph substrate, mastery, the goal-projection Universe) now lives in
[knowledge-model.md](knowledge-model.md) -- read that first. The old strict-tree hierarchy,
all-corpus Universe, forced clustering, and the LangGraph framing in earlier versions of this doc are
**superseded**; what remains below is the still-true pipeline craft.

The concept layer is the spine that connects abstract material down to generatable text and up to
mastery. If a piece of data isn't needed by a downstream use case, we don't store it.

## Pipeline shape (built)

A **plain sequential runner** (`app/workflows/concept_pipeline.py`), not LangGraph -- a StateGraph
dropped the `hierarchy` key, so the pipeline is explicit and ordered. Each stage is an independent,
swappable node in `app/workflows/concept_nodes/`, inspectable via `make concepts-dryrun`:

```
select_entities -> embed_entities -> build_hierarchy -> label_levels -> score_concepts -> persist_concepts
```

Tunable knobs live in `concept_nodes/_shared.py::PIPELINE_CONFIG`.

## 1. Entity selection -- relevance starts here

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

## 2. Embeddings -- context, not bare names

Cluster on **context embeddings**, not the entity string. Each entity's vector = centroid of the
**chunk** vectors where it occurs (bge-small, 384-dim; matched via `chunk.entities_text`, capped per
entity; `vector_store.fetch_chunk_vectors` bulk load). "Transformer" in an ML book vs an electrical
text then separate correctly. Name-embedding fallback; degrades if no DB. (This fixed the "bloom
filter" clustering.)

## 3. Clustering -- emergent, not a forced count

One average-linkage cosine dendrogram (`scipy.cluster.hierarchy.linkage(method='average',
metric='cosine')`); cut **once** into concepts via `fcluster maxclust` (gap/percentile cuts were
pathological on bge-small). The **number of concepts is an outcome of the data, never a forced
`n_clusters`**. Edges are k-NN (top-k above a cosine cutoff), **not** all-pairs (all-pairs exploded to
a 75k-edge hairball). The sun/medoid of a cluster = its most-central member.

> **Flat layer (2026-06-24).** The galaxy/constellation tiers (the Knowledge Universe "sky") were
> removed: nothing read them once the Universe surface was retired. `build_hierarchy` now emits a
> single concept level + RELATED_TO edges; `label_levels` labels concepts by their sun (no LLM);
> `persist` writes level-2 concepts with no parent chain. A `verify`/dedup node (merge near-duplicates
> by centroid; under-claim over mislabel) still lands before persist.

## 4. Model-routed LLM labelling

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

## 5. Stable identity -- so re-extraction doesn't reset the user

A concept's **slug derives from its lineage signature** (a hash over its sorted member-entity set),
**not** from the volatile LLM label. Consequences:

- The same cluster keeps the **same slug** across regenerations -> user overrides (rename/merge/reject),
  mastery, and **goal bindings** persist (re-applied/keyed by slug, I-22).
- A label change ("Data Systems" -> "Data Engineering") is a relabel of the same identity, not a new
  concept.

This is what makes `make concepts` safe to run repeatedly (manual + idle/background).

## 6. Persisted lineage -- the bridge to material

The abstraction lineage is persisted, not thrown away -- it is the single source for generation
material, mastery, evidence receipts, and doc-overview membership:

- `concepts.parent_id` (SQLite) is a **derived layout cache** only; membership truth is Kuzu edges
  (knowledge-model.md, I-23).
- `(:Concept)-[:PROMOTED_FROM]->(:Entity)` -- which entities make up a concept.
- `(:Concept)-[:EXTRACTED_FROM]->(:Document)` -- availability/provenance.
- entity->chunk occurrence index (from `chunk.entities_text`) -- resolves a concept to its passages
  for generation and evidence; `evidence_json = {chunk_ids, document_ids, members}`.

## 7. Observability -- every stage is inspectable

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

## 8. Known perf gotchas

- Full-text entity->chunk matching OOM-killed `make concepts` (exit 143) -> use the short
  `entities_text`, not full chunk text.
- All-pairs concept edges exploded persist + produced a hairball -> k-NN with a cutoff.
- Never run heavy concept work in the live server lifespan -- sync Kuzu starves the event loop. Offline
  `make concepts` (server stopped) is the path; an idle/background trigger is still TODO.
