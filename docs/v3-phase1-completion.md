# V3 Phase 1 Completion Doc

**Branch:** `ralph/luminary-v3`
**Phase:** V3 Phase 1 - Note Organization and Knowledge Graph
**Stories:** S161-S170 (10 stories, priorities 1-10)
**Status:** COMPLETE -- all 10 stories pass, gate cleared 2026-03-26

This document describes what Phase 1 delivers, how to validate that each story is
working end-to-end, and the gate criteria for declaring Phase 1 complete.

---

## What Phase 1 Delivers

### The fundamental shift

Before Phase 1, notes are a flat list with a single freeform `group_name` label, flat
unindexed JSON tags, and zero presence in the knowledge graph. After Phase 1, notes
become a first-class part of the knowledge system: they live in typed collections,
carry a managed tag vocabulary, are connected to the entity graph, and drive their own
study decks.

---

### Notes tab

**Sidebar before:** flat list of group_name strings + flat tag buttons.

**Sidebar after:**
- **Collections tree** -- collapsible 2-level hierarchy (e.g. "Physics > Quantum
  Mechanics (18)"). Colored square icons. Drag a note row onto a collection item to
  assign it. A note can belong to multiple collections simultaneously.
- **Tags tree** -- collapsible hierarchy (e.g. "programming (34) > python (18), go (9),
  rust (7)"). Gear icon on hover: rename, re-parent, merge into another tag. Clicking
  any node filters notes using prefix matching -- clicking "programming" shows all notes
  tagged `programming/*`.
- **Suggested Collections** section (below Collections) -- visible when HDBSCAN
  clustering has produced pending suggestions. Each card shows the cluster name, note
  count, confidence bar, and 3-note previews. Accept/Reject buttons.

**Note editor before:** flat tag chip input, single group_name dropdown.

**Note editor after:** TagAutocomplete with hierarchy awareness (typing `ml/` shows
children of `ml`), plus a scrollable checkbox list of all collections with
immediate-save on check/uncheck.

**Note cards before:** flat opaque tag chips.

**Note cards after:** `root/child` breadcrumb style.

---

### Viz tab

**Before:** Knowledge, Call Graph, Learning Path modes -- all driven by book entities.

**After:** a fourth **Tags** mode. Nodes are canonical tags sized by note count, colored
by parent tag family. Edges are co-occurrences (two tags on the same note). Clicking a
tag node fires a cross-tab navigation event that activates the Notes tab with that tag
pre-applied as a filter.

---

### Knowledge graph (Kuzu)

**Before:** Entity, Document, DiagramNode types and 19 relationship types -- all derived
from ingested books.

**After:** a `Note` node type with three new edge types:

| Edge | Meaning |
|---|---|
| `WRITTEN_ABOUT` | Note -> Entity (GLiNER extracted from note content, async on save) |
| `TAG_IS_CONCEPT` | Note -> Entity (tag string matches an Entity.name, case-insensitive) |
| `DERIVED_FROM` | Note -> Document (when note was taken while reading a specific book) |

The chat graph `notes_node` enriches note context snippets with linked entity names,
giving the LLM better context for answers.

---

### Study tab

**Before:** decks organized entirely by document; no concept of a notes deck.

**After:**
- Collection decks appear alongside document decks (folder icon vs book icon).
- `GenerateFlashcardsDialog` has a "By Collection" tab with a tree picker and an
  "{n} notes, {m} already covered" preview before generating.
- Generation is incremental -- notes whose content hash already matched a card in this
  deck are skipped.

---

### Performance

- Note vector dimension fixed: 384-dim schema corrected to 1024-dim (bge-m3 output).
  On first run after S170, `note_vectors_v2` is dropped and recreated; all notes
  are re-embedded via `POST /admin/notes/reindex`.
- Tag queries indexed: `idx_note_tag_index_tag_full` and `idx_note_tag_index_note_id`
  on `note_tag_index` table. p95 < 100ms at 1,000 notes.

---

## Story-by-Story Validation Checklist

Use this checklist to confirm each story is working end-to-end in the running app
(not just that tests pass). All items must be checked before declaring Phase 1 complete.

### S161 -- Note Collections Schema and API

- [x] Open Notes tab -- sidebar shows "Collections" section (not "Groups")
- [x] Click "New Collection" -- dialog opens with name, description, color picker,
  parent collection selector
- [x] Create "Physics" collection (top-level, blue)
- [x] Create "Quantum Mechanics" collection with parent "Physics"
- [x] Sidebar shows "Physics" with chevron; expand shows "Quantum Mechanics" indented
- [x] Assign an existing note to "Quantum Mechanics" -- note count increments on both
  "Quantum Mechanics" and "Physics"
- [x] Assign the same note to a second collection -- note appears in both
- [x] Click "Physics" -- main panel shows only notes in Physics or any child collection
- [x] Click "Quantum Mechanics" -- main panel shows only notes in that collection
- [x] Delete "Physics" -- dialog warns "Notes are not deleted"; notes survive deletion
- [x] `GET /collections/tree` returns nested JSON in browser/curl

### S162 -- Hierarchical Tags

- [x] Create a note with tags `programming/python` and `programming/go`
- [x] Tags sidebar shows "programming (2)" collapsible; expand shows "python (1)", "go (1)"
- [x] Click "programming" -- main panel shows both notes (prefix match)
- [x] `GET /tags/autocomplete?q=prog` returns "programming", "programming/python",
  "programming/go"
- [x] `GET /notes?tag=programming` returns both notes
- [x] Delete the note -- CanonicalTagModel note_count decrements to 0 for both tags

### S163 -- Notes as Kuzu Graph Nodes

- [x] Save a note with content mentioning an entity already in the Kuzu graph (e.g.
  an author name or concept from an ingested book)
- [x] `GET /notes/{note_id}/entities` returns at least one entity with edge_type
  `WRITTEN_ABOUT` and a confidence score
- [x] Save a note with tag matching an existing entity name -- entities endpoint shows
  a `TAG_IS_CONCEPT` edge for that tag
- [x] Save a note with `document_id` set -- entities endpoint shows `DERIVED_FROM`
  edge to the correct document
- [x] Delete the note -- subsequent GET /entities returns 404 or empty list
- [x] Ask the chat a question related to the entity mentioned in the note -- answer
  references "[From your notes]" context with entity names appended

### S170 -- Performance Refactor

- [x] Check backend startup logs -- confirm no "note_vectors_v2 schema mismatch" warning
  (or if it does appear on first run, confirm it only appears once and the table is
  recreated)
- [x] `POST /admin/notes/reindex` returns `{queued: true, total_notes: N}`
- [x] After reindex completes, `GET /notes/search?q=<term>` returns semantically
  relevant results (previously unreliable due to dim mismatch)
- [x] `GET /notes?tag=programming` responds in under 200ms with 100+ notes in the DB

### S164 -- Collections UI

- [x] CollectionTree renders with correct note counts and nesting
- [x] Drag a note row from the table onto a collection item in the sidebar -- note
  count increments; note appears when that collection is filtered
- [x] NoteEditorDialog "Collections" section shows all collections as checkboxes;
  current memberships pre-checked
- [x] Check a collection in NoteEditorDialog -- POST fires immediately without clicking
  Save on the note content
- [x] group_name input is gone from NoteEditorDialog (deprecated)

### S165 -- Hierarchical Tag Browser UI

- [x] TagTree renders in Notes sidebar below Collections; shows correct nesting and
  counts
- [x] Gear icon on a tag opens management panel; rename updates the tree
- [x] "Merge into..." combobox -- merge "ml" into "machine-learning"; toast shows "{n}
  notes updated"; "ml" disappears from tag tree
- [x] NoteEditorDialog tag input replaced by TagAutocomplete; typing `prog` shows
  hierarchy-aware dropdown; typing `programming/` shows only children
- [x] Note cards in list view show `root/child` breadcrumb style (not flat chips)

### S167 -- Tag Co-occurrence Graph

- [x] Viz tab shows "Tags" button in mode selector
- [x] Tags mode renders a Sigma.js graph with nodes sized by note count
- [x] Two tags that appear together on multiple notes are connected by an edge
- [x] Click a tag node -- Notes tab activates with that tag filter applied
- [x] Empty state (< 3 tags): placeholder message shown instead of blank canvas

### S168 -- Smart Tag Normalization

- [x] Notes sidebar "Tags" section shows wrench icon button
- [x] Click wrench -- spinner appears; after scan, NormalizationDrawer opens
- [x] Drawer shows similarity %, note count, and Accept/Reject for each suggestion
- [x] Accept a suggestion -- affected notes updated; source tag disappears from tree
- [x] Toast shows "{n} notes updated"
- [x] Re-scan immediately after -- already-aliased tags not re-suggested

### S166 -- Semantic Clustering

- [x] "Auto-organize" (Wand2 icon) button appears in Collections section
- [x] Click Auto-organize -- spinner while queued; "Suggested Collections" section
  appears below Collections tree
- [x] Each suggestion card shows: name, note count, confidence bar, 3 note previews
- [x] Accept a suggestion -- new collection appears in CollectionTree immediately;
  notes are assigned
- [x] Reject a suggestion -- card fades out
- [x] Click Auto-organize again within 1 hour -- system returns cached result (no
  duplicate suggestions created)

### S169 -- Collection-Based Flashcard Generation

- [x] Open GenerateFlashcardsDialog from Notes tab -- "By Collection" tab is present
- [x] Select a collection -- "{n} notes, {m} already covered" line appears
- [x] Generate flashcards -- deck named after the collection, not "notes"
- [x] Open Study tab -- collection deck appears with folder icon alongside document decks
- [x] Run generate again on the same collection with unchanged notes -- skipped count
  equals previous created count (no duplicates)
- [x] Edit a note in the collection and re-generate -- that note's card is regenerated;
  unchanged notes still skipped

---

## Phase 1 Completion Gate

All of the following must be true before Phase 1 is declared complete:

- [x] All 10 stories have `passes: true` in `prd-v3.json`
- [x] All items in the validation checklist above are checked
- [x] `uv run pytest` passes with no regression (count >= baseline)
- [x] `uv run ruff check .` exits 0
- [x] `npx tsc --noEmit` exits 0
- [x] All 10 smoke scripts (`scripts/smoke/S161.sh` -- `scripts/smoke/S170.sh`) exit 0
- [x] `POST /admin/notes/reindex` has been run once against the live database to correct
  the vector dimension for any pre-existing notes

Once the gate is passed, move this file to `docs/completed/v3-phase1-completion.md`
and proceed to Phase 2.

---

## What Phase 1 Does Not Deliver (Phase 2 scope)

The following capabilities are natural next steps but are explicitly out of Phase 1 scope:

1. **Note-to-note explicit links** -- Zettelkasten-style `[[note title]]` bidirectional
   links. Phase 1 connects notes to entities and collections but not to each other
   directly.

2. **Note nodes in Knowledge/Learning Path Viz modes** -- Note nodes are in Kuzu after
   Phase 1 but do not yet appear in the Knowledge or Learning Path graph views alongside
   Entity and Document nodes.

3. **Collection health report** -- analogous to the Deck Health report (S160): cohesion
   score, orphaned notes, notes with no flashcards, stale notes. Not in Phase 1.

4. **Export** -- collections as Obsidian-compatible Markdown vault or as Anki decks.
   Not in Phase 1.

5. **Multi-document notes** -- a note that spans or compares two books has no explicit
   cross-document model yet. Phase 1 gives a note a single `document_id`; a join-note
   linking two entities from different books has no home.

These five items are the seed stories for V3 Phase 2.
