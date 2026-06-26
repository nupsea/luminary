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
space** -- directly comparable to chunks and to bge-small query embeddings. A labs upgrade
synthesizes `label + gloss + top evidence` and re-embeds it with the same chunk embedder for higher
quality (staying in one space). Notes live in a separate 1024-dim bge-m3 space, so note->concept
matching embeds the note text with the chunk embedder (bge-small) or falls back to title/lexical.

Used for: Entity->Concept dedup, note->concept link chips (degraded path), candidate-concept
seeding, scope->concept resolution. **Never** a retrieval primary -- chunk vectors + FTS5 + graph
(RRF) stay the RAG backbone.

### OKF projection (derived -- Phase 5)

One Markdown file per concept: front-matter from the SQLite state, body = evidence quotes, links =
Kuzu edges. See [okf.md](okf.md). The file is **not** the truth; a user edit becomes an `override`
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
IF Feynman (labs) enabled AND a teach-back exists:
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
