/**
 * Single source of truth for "is this document ready for learning features?".
 *
 * A document is ready once its ingestion pipeline reaches the `complete` stage:
 * sections, chunks, embeddings, and graph nodes are all populated. Before
 * that, downstream features (Study, Viz, Chat, flashcards, search) silently
 * break because their data isn't there yet. The library is the only surface
 * that should display in-progress documents — every other view defaults to
 * ready docs only.
 *
 * Predicate is intentionally minimal so the same import works against
 * DocumentListItem, DocumentDetail, or any subset that carries `stage`.
 */
export interface DocumentReadinessShape {
  stage: string
}

export function isDocumentReady<T extends DocumentReadinessShape>(doc: T | null | undefined): boolean {
  return !!doc && doc.stage === "complete"
}

export function isDocumentProcessing<T extends DocumentReadinessShape>(
  doc: T | null | undefined,
): boolean {
  if (!doc) return false
  return doc.stage !== "complete" && doc.stage !== "error"
}

export function isDocumentErrored<T extends DocumentReadinessShape>(
  doc: T | null | undefined,
): boolean {
  return !!doc && doc.stage === "error"
}

/**
 * True once the document has graph data populated in Kuzu.
 *
 * The ingestion pipeline writes Entity / MENTIONED_IN nodes during the
 * `entity_extract` stage (60% progress). Docs that have advanced past that
 * stage have a viewable graph even if the doc as a whole isn't `complete`
 * yet. Used by Viz so docs still finishing embedding / indexing /
 * enriching surface in the picker instead of being hidden until the very
 * end of ingestion.
 */
const _GRAPH_READY_STAGES = new Set([
  "entity_extract",
  "embedding",
  "indexing",
  "enriching",
  "complete",
])

export function hasGraphData<T extends DocumentReadinessShape>(
  doc: T | null | undefined,
): boolean {
  return !!doc && _GRAPH_READY_STAGES.has(doc.stage)
}
