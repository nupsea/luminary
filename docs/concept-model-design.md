---
description: The Concept knowledge model -- how higher-level concepts are derived, stored with lineage, linked to material, and used for mastery + generation. Read before any concept-extraction work.
---

# Concept Knowledge Model -- design

The concept layer is not a clustering trick that produces pretty labels; it is the
**spine that connects abstract themes down to generatable material and up to mastery**.
Every design choice below exists to serve a downstream use case. If a piece of data
isn't needed by a use case, we don't store it; if a use case can't be served, the model
is wrong.

## 0. The Universe is a nested hierarchy with distance-encoded edges (recalibrated)

A flat "themes + sub-concepts" model renders as a hairball. A real **Universe** is nested,
and the *distance* between things is the whole point:

```
Galaxy        domain        "Data Engineering", "Philosophy"      far apart, NO edges between
  Constellation  theme       "Storage Formats", "Dharma"          thin link up to its galaxy
    Solar system  concept     a sun (central idea) + orbiting      strong links within, to the sun
      planets     entities/detail                                  the concept's material
```

Edge semantics encode proximity (the user's spec):
- **Within a solar system** → strong, short links to the sun (closely related).
- **System → constellation → galaxy** → progressively *thinner* structural links.
- **Across galaxies** → **no link** (unrelated domains must not be connected).

This falls out of a **single hierarchical-clustering dendrogram** cut at multiple heights.
The merge *height* in the dendrogram IS the distance: galaxies merge only near the root
(large distance → no lateral edge), solar systems merge low (small distance → strong
edge). One tree → the levels nest consistently (a concept can't belong to two galaxies).

Implementation: `scipy.cluster.hierarchy.linkage(seeds, method='average', metric='cosine')`
once, then `fcluster` at three thresholds (galaxy > constellation > concept). A leaf's
(galaxy, constellation, concept) all come from the same tree → guaranteed nesting.
Lateral edges are drawn only between nodes whose **lowest common ancestor is at/below the
constellation** (so cross-galaxy pairs get none); edge weight = cosine similarity (link
strength). The **sun** of a solar system = its highest-salience / most-central member.

`ConceptModel.level`: **0 = galaxy, 1 = constellation, 2 = concept (studyable)**. Mastery
lives on level-2 concepts (you study a solar system); galaxies/constellations are
containers whose mastery is a rollup. Each level is named bottom-up by the LLM (concept →
constellation → galaxy), the most abstract names using the strongest model.

The rest of this doc (lineage, identity, mastery, generation) is unchanged -- it now
hangs off level-2 concepts; galaxies/constellations are additional container rows with
`parent_id` chains. §4's clustering is superseded by this dendrogram approach.

## 1. The layered model -- and the lineage is STORED

```
Document ─▶ Chunk ─▶ Entity (GLiNER, typed)         L0  raw mentions (Kuzu, exists)
                         │ promote (cluster)
                         ▼
                     Sub-concept   (Concept, level 1)  L1  a tight, coherent idea in a doc
                         │ abstract (roll up)
                         ▼
                     Theme         (Concept, level 0)  L2  a cross-document topic ("Data Systems")
```

**The abstraction lineage is persisted, not thrown away.** A theme stores its child
sub-concepts; a sub-concept stores its member entities; an entity stores the chunks it
occurs in. This Theme→Sub→Entity→Chunk→Document chain is the **single source** for:
generation material, mastery rollup, evidence receipts, doc-overview membership, and
incremental re-abstraction. Without it, a "concept" is just a label you can't study,
score, or recompute. (This is precisely what the first implementation got wrong: it
stored labels with no lineage.)

Stored edges (Kuzu) / refs (SQLite):
- `(:Theme)-[:CONTAINS]->(:Sub)` — hierarchy (also `concepts.parent_id` in SQLite).
- `(:Sub)-[:PROMOTED_FROM]->(:Entity)` — which entities make up this concept.
- `(:Concept)-[:EXTRACTED_FROM]->(:Document)` — availability/provenance.
- `(:Concept)-[:RELATED_TO]->(:Concept)` — lateral links (co-occurrence-derived).
- `entity → chunk` occurrence index (from `chunks.entities_text` / NER offsets) — the
  bridge to text. Computed/stored so a concept resolves to chunks in O(1)-ish.

## 2. Entity selection -- relevance starts here

Not every NER entity is a concept seed. GLiNER emits PERSON, organization, location,
date, etc. (`ner.py ENTITY_TYPES`). Those produce the "Iranian artists" noise.

- **Keep** concept-bearing types: `_TECH_ENTITY_TYPES` (CONCEPT, METHOD, DATA_STRUCTURE,
  ALGORITHM, TECHNOLOGY, …) + domain nouns; **drop** PERSON / ORGANIZATION / LOCATION /
  DATE / misc by default (configurable per corpus — a history library may want PERSON).
- **Frequency floor**: drop hapax/near-hapax entities (mentioned once) — low salience.
- This filter is deterministic and is the single biggest relevance lever.

## 3. Embeddings -- context, not bare names

Cluster on **context embeddings**, not the entity string. Each entity's vector =
centroid of the chunk vectors where it occurs (reuse the chunk LanceDB vectors + the
centroid we already build). "Transformer" in an ML book and "transformer" in an
electrical text then separate correctly; a bare-name embedding can't tell them apart.

## 4. Clustering -- coherence-gated, not a forced count

Two passes, but **never force a fixed cluster count**:
- **L1 (within document/section):** agglomerative with a cosine-distance *threshold* →
  however many tight clusters genuinely cohere. Singletons stay singletons (or attach to
  their nearest cluster only within the threshold).
- **L2 (cross-document roll-up):** cluster L1 centroids with a *threshold* too; the
  number of themes is an *outcome*, not an input. Then **cap by salience** for display
  (Universe shows the top ~N), but keep all stored (zoom reveals the rest).

A forced `n_clusters=25` is what merged comedy with architecture. Threshold + salience
cap replaces it.

## 5. Multi-step LLM abstraction -- the right model per step

The LLM works in **stages**, with model choice matched to the job (via LiteLLM routing):

| Step | Job | Tool / model | Cost |
|---|---|---|---|
| A. cluster | group entities | embeddings + co-occurrence (no LLM) | cheap, local |
| B. label sub-concept | name a tight cluster | heuristic medoid, or a **small/fast** model | low |
| C. abstract | group sub-concepts into themes + name them | a **stronger reasoning** model, given labels+entities+sample evidence | the expensive step, ~N calls |
| D. verify | coherence check, merge near-dupes, reject incoherent ("under-claim over mislabel") | reasoning model, batched | bounded |

Principles: only Step C/D need the capable model; A is free; B can be heuristic to cap
cost. All steps run **offline/idle, throttled** (semaphore + paced), never on the live
loop. The model proposes; nothing is asserted as fact (constitution 5) — low-confidence
groupings become `proposed`/`candidate`, not `confirmed`.

## 6. Stable identity -- so re-abstraction doesn't reset the user

A concept's **slug (identity) derives from its lineage signature** (a hash of its sorted
member-entity set), **not** from the volatile LLM label. Consequence:
- The same cluster keeps the **same slug** across regenerations → user overrides
  (rename/merge/reject) and mastery **persist** (re-applied/keyed by slug, I-22).
- A label change ("Data Systems" → "Data Engineering") is just a relabel of the same
  identity, not a new concept.

This is what makes regeneration safe to run repeatedly (manual + idle/background).

## 7. Mastery & conceptual knowledge -- computed bottom-up through the lineage

```
card ── mapped via its chunk/entity ──▶ sub-concept
mastery(sub)   = fsrs_retrievability(sub.cards) blended with calibration       # I-19
mastery(theme) = salience-weighted mean of child sub masteries
warmth(concept)= clamp(1 - daysSince(last_reviewed)/18)
coverage(concept) = fraction of its material (chunks) with >=1 card            # "how studied"
gap(concept)   = on a goal route AND (no covering doc OR coverage ~ 0)
```

All of these are pure functions of the **stored lineage** + FSRS. They're written to the
concept row by the assessment pipeline (never text-matched). A session updates the
sub-concepts it touched; theme mastery and collection/goal rollups move automatically.

## 8. Generation -- a concept becomes studyable via its material

"Quiz me on this concept" / "Generate questions" resolves: concept → lineage → chunks →
generate cards from that text. New cards map back to the sub-concept (mapped); cards that
match no concept are unmapped (two-lane model). This is why the entity→chunk bridge (§1)
must be stored — generation needs the actual passages, not the label.

## 9. Use cases this model must serve (and where each touches the data)

| Use case | Needs |
|---|---|
| Universe render | themes (L2) + warmth/mastery/salience + RELATED_TO edges + hierarchy |
| Study/quiz from a concept | lineage → chunks (material) → generator |
| Mastery rollup (concept/collection/goal) | card→sub→theme lineage + FSRS |
| Doc overview membership | concept ↔ document via EXTRACTED_FROM |
| Note → concept link | concept centroid + lexical, vs note content |
| Goals / gaps / plan | target concepts; gap = route concept w/ no material |
| Corrections survive re-parse | stable slug identity + overrides (§6) |
| Incremental re-abstraction | re-cluster only changed docs; attach/spawn; keep state |
| OKF projection | one file per concept: frontmatter + evidence + lineage links |

## 10. Gap audit -- current implementation vs this design

| Aspect | Design | Current `concept_extraction_service` | Gap |
|---|---|---|---|
| Entity type filter | keep concept types, drop PERSON/ORG/… | uses ALL entity types | **missing** |
| Embeddings | context centroid | bare entity name | **wrong** |
| Clustering | coherence threshold + salience cap | forced `n_clusters=25` | **wrong** |
| Entity lineage stored | `PROMOTED_FROM` + entity→chunk | only `EXTRACTED_FROM` (doc); no entity link | **missing** |
| Stable identity | slug = lineage signature | slug = LLM label (changes each run) | **wrong** (breaks overrides/mastery persistence) |
| LLM steps | A→B→C→D, model-routed | single naming call | **partial** |
| Mastery rollup | bottom-up via lineage | legacy text-match `compute_mastery` | **not wired to concepts** |
| Generation from concept | via lineage → chunks | study_assembler generates from doc/note, not concept material | **missing** |
| Incremental | re-cluster changed docs | full wipe+rebuild | **missing** |
| Evidence | passages from lineage chunks | empty `[]` | **missing** |

**Conclusion:** the current implementation is the right *shape* (layers, hierarchy,
offline regenerate) but is missing the parts that make concepts *correct and useful* —
type filtering, context embeddings, coherence clustering, stored entity lineage, stable
identity, and bottom-up mastery. Those are the work, in roughly this dependency order:

1. Entity selection (type filter + frequency floor) — biggest relevance win, deterministic.
2. Context embeddings + coherence-gated clustering — coherent clusters.
3. Stored entity lineage (`PROMOTED_FROM` + entity→chunk index) — unlocks generation + mastery.
4. Stable lineage-signature identity — safe regeneration + override/mastery persistence.
5. Multi-step LLM (label → abstract → verify), model-routed + throttled — theme quality.
6. Bottom-up mastery rollup + concept-scoped generation — the loop closes.
7. Incremental re-abstraction + idle/background trigger.
8. Then the Universe UI (canvas, to `mind.jsx` fidelity) renders a model worth looking at.

## 11. Architecture -- a pluggable node workflow (LangGraph)

The pipeline is built as a **LangGraph `StateGraph`** (same pattern as the ingestion
workflow: `workflows/concept_pipeline.py` + one node fn per file in
`workflows/concept_nodes/`). Each stage is an **independent, swappable node** with a
clear input/output contract on a shared `ConceptPipelineState`. This is deliberate:
every reasoning stage can be evaluated, replaced, or A/B'd in isolation as we explore
Lumen's reasoning — e.g. swap the clustering node (HDBSCAN ↔ community detection),
swap the labeler (heuristic ↔ small model ↔ big model), insert a new verification node —
without touching the rest.

```
select_entities → embed_entities → cluster_subconcepts → rollup_themes
   → label (B/C) → verify (D) → build_lineage → persist
```

| Node | Contract (in → out) | Swappable alternatives |
|---|---|---|
| `select_entities` | docs → typed, frequency-filtered entities/doc | type sets, frequency floor, salience priors |
| `embed_entities` | entities → vectors | context-centroid ↔ name ↔ definition-augmented |
| `cluster_subconcepts` | vectors → per-doc clusters | agglomerative ↔ HDBSCAN ↔ graph community |
| `rollup_themes` | sub centroids → themes | threshold ↔ count ↔ LLM-grouping |
| `label` | clusters → names | heuristic medoid ↔ fast model ↔ reasoning model |
| `verify` | themes → merged/validated | rule-based ↔ LLM coherence/dedup |
| `build_lineage` | clusters → Theme→Sub→Entity→Chunk refs + salience | — |
| `persist` | lineage → SQLite+Kuzu+LanceDB, stable slug, overrides | — |

Each node is pure w.r.t. its inputs where possible (clustering/labeling), with side
effects isolated to `persist`. A node can be disabled/replaced via the graph builder.

## 12. Observability -- every stage is inspectable

Verification must not require reading code. Each node:
- **Logs** structured, human-readable progress: counts in/out, what was kept vs dropped
  and *why* (e.g. "dropped 1,910 entities: PERSON 740, ORGANIZATION 520, freq<2 650"),
  cluster sizes + cohesion scores, cluster→label with the model used, theme membership,
  salience/mastery/warmth values, lineage fan-out (theme → N subs → M entities → K chunks),
  and persisted slug + identity hash.
- **Accumulates** a structured `diagnostics` block in the state (per node), so the whole
  run is dumpable as one report.

`make concepts` supports:
- `--dry-run` — run every node *except* `persist`; dump the full diagnostics report
  (entities kept/dropped, every cluster with its members + scores, proposed themes with
  their member entities + chosen labels). This is the relevance-tuning loop: judge the
  output on real data before touching the DB.
- `--verbose` — per-node detail to stdout.
- a written report at `.luminary/concepts/last_run.json` for after-the-fact inspection.

Principle: if a theme looks wrong, the logs must show *why* — which entities fed it,
which step grouped them, and what score let it through.
