# Knowledge Universe — Remaining Development Roadmap

Status as of this branch (`feat/knowledge-universe`). The concept model and the navigable
Universe are **done and green**; this doc tailors the rest of the work into gated
milestones. Each gate ends shippable, keeps `make ci` green, and honours the invariants.

## Done (foundation)

- **Concept primitive** across SQLite (truth) + Kuzu (topology) + LanceDB (centroid) with
  stable lineage-signature slugs, parent_id chains, level 0/1/2, override-safe regen.
- **Concept pipeline** (swappable nodes): `select_entities` (type + junk filter) →
  `embed_entities` (context-centroid) → `build_hierarchy` (maxclust galaxy/constellation/
  concept, outlier-merge, ≥5 domains) → `label_levels` (per-tier LLM naming) →
  `persist_concepts`. Fully inspectable via `make concepts-dryrun`. See
  `docs/concept-model-design.md`.
- **Universe lens**: nested sky with drill-down (galaxy → constellation → concept),
  k-NN edges, warmth shading, breadcrumb, star panel → launcher.
- Phases 0–4 of the original plan (`concepts` schema, Study Launcher + entry points, ingest/
  doc-overview/collections, notes Lane-B + chips, Universe lens).

---

## Gate A — The Universe is *live and studyable* (NEXT)

Right now the sky is a beautiful map but a dead-end loop: container stars (galaxy/
constellation) can't be studied, mastery doesn't flow up the hierarchy, so upper stars never
warm. Gate A closes the learning loop end-to-end.

1. **Container study (scope_resolver).** `resolve_concept` detects level: a level-0/1 node
   expands to its descendant level-2 concepts (galaxy → its constellations' concepts;
   constellation → its concepts), weakest-first. Leaf concept behaves as today. New graph/
   SQL: `descendant_concept_ids(node_id)`.
2. **Bottom-up mastery rollup.** When a concept's `set_learning_state` lands, recompute its
   parent constellation's mastery = salience-weighted mean of child concepts, and the
   galaxy = mean of its constellations; `last_reviewed` rolls up as max. So studying a leaf
   visibly warms its constellation and galaxy. One helper, called from the write-back path
   and the backfill.
3. **Mastery read-flip (verify).** Progress/Universe/Map read the stored concept scalar
   (Phase-4 deferred check); container nodes show rolled-up mastery/warmth.
4. **Concept evidence → generation.** `study_assembler` uses a concept's `evidence_json`
   chunk_ids as grounding when generating questions for a concept scope (better than scope
   text match).

**Done-bar:** click any star (galaxy/constellation/concept) → Study this → a valid session
assembles; completing it moves the concept's mastery AND visibly warms its parents on the
Universe; `make ci` green; tests for descendant-resolve + rollup.

## Gate B — The Universe *looks* like the vision

Visual polish to `docs/handoff/prototype/luminary-v4/mind.jsx` fidelity over the current SVG:
radial-gradient deep space, warmth-lit star glow, galaxy hulls/labels at the sky level,
constellation grouping on drill-in, distance-styled edges (thick intra, thin inter), gentle
parallax. Keep it SVG/canvas (no new graph engine); keep loading/empty states.

**Done-bar:** the sky reads as a universe (named galaxy regions, glowing stars, layered
edges); drill-in animates; still meaningful with the linker off.

## Gate C — OKF portable layer (original Phase 5)

`okf_exporter` + `POST /okf/export` (public) → `.luminary/okf/{index,concepts/,learner/,
sources/}`; `okf_context` (scope → grounding string woven into QA/assembler prompts,
model-agnostic); `okf_importer` + `POST /okf/import` → upsert as proposed/candidate through
the existing "review what Lumen found" surface. Strictly local.

**Done-bar:** export round-trips through import; QA grounding identical across Ollama/cloud;
imports land candidate + correctable.

## Gate D — Plan (labs) + re-tiering + release (original Phase 6)

`pages/Plan` over goals+mastery (`plan_router`: target concepts → topological weekly buckets
→ mastery gates); labs-gated surface. Apply D3 manifest re-tiering. Then 3.3.B release
sign-off (tag/push/merge — awaiting user).

**Done-bar:** goal → route → gates work with zero docs and gappy weeks; `make lint` green;
public bundle excludes retired-to-dev code.

## Cross-cutting / deferred

- **Idle/background regeneration** — throttled auto-run of `make concepts` during free LLM
  time + incremental re-cluster of changed docs (resource-bounded). Pairs with Gate A.
- **Naming polish** — model routing (fast vs reasoning) per tier; prompt tuning if labels
  read oddly after a merge.
- task #18 tail — deep card-set handoff into the Study page.

## Tunable knobs (concept pipeline)

In `app/workflows/concept_nodes/_shared.py::PIPELINE_CONFIG`: `galaxy_k_range`,
`min_galaxies`, `min_galaxy_concepts`, `constellation_k_range`, `max_concepts_cap`,
`concept_edge_cutoff`/`concept_edge_top_k`, `galaxy_edge_cutoff`. Embedding coverage knob:
`embed_entities._MAX_CHUNKS_PER_ENTITY`.
