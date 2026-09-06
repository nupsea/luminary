// When the library list should keep refetching.
//
// The enrichment toast polled every 5s and the document cards polled not at all,
// so a card sat at whatever state it held when the page loaded: it read
// "Analysis complete" while the toast beside it counted down tasks still running
// on that same document. The badge was never wrong, it was frozen.
//
// Decided from the rows themselves rather than from a separate "is anything
// running" flag, so the page stops polling exactly when it has nothing left to
// show, and cannot disagree with what it is rendering.

/** The fields of a library row this decision reads. */
export interface PollableDocument {
  stage: string
  enrichment_status?: string | null
}

/** Stages with nothing further to report. Anything else is still in flight. */
const SETTLED_STAGES = new Set(["complete", "failed"])

/** Enrichment states with work outstanding. `skipped` is settled, not pending. */
const BUSY_ENRICHMENT = new Set(["pending", "running"])

export const LIBRARY_POLL_MS = 5_000

export function isDocumentBusy(doc: PollableDocument): boolean {
  if (!SETTLED_STAGES.has(doc.stage)) return true
  return BUSY_ENRICHMENT.has(doc.enrichment_status ?? "")
}

/**
 * The refetch interval for a page of library rows, or false to stop.
 *
 * Returning false rather than a large number matters: a library that is entirely
 * settled should make no requests at all, and this page is the app's landing spot
 * for long stretches.
 */
export function libraryRefetchInterval(items: PollableDocument[] | undefined): number | false {
  return (items ?? []).some(isDocumentBusy) ? LIBRARY_POLL_MS : false
}
