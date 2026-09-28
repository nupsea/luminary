// Whether the library page should snapshot the deep-link params it was opened with.
//
// The capture effect used to run only when the document changed:
//
//     if (!docParam || docParam === activeDocumentId) return
//
// which is false at exactly the moment it matters. `navigateToCitation` sets the
// active document in the store *before* it navigates, so by the time the library
// page reads it the ids already match and the effect returns without snapshotting
// anything -- section_id, chunk_id and the citation snippet were all dropped, and
// a cited passage opened the document at wherever it was last left.
//
// The same held for a citation clicked while already reading that document: the
// ids match legitimately, and re-targeting within the document never happened.
//
// So the question is not "did the document change" but "were we handed somewhere
// to go".

/** Params that name a place in the document rather than the document itself. */
const DEEP_LINK_PARAMS = ["section_id", "chunk_id", "page", "search", "note"] as const

export interface ParamReader {
  has(name: string): boolean
}

export function hasDeepLinkParams(params: ParamReader): boolean {
  return DEEP_LINK_PARAMS.some((name) => params.has(name))
}

/**
 * Whether to snapshot and open.
 *
 * Returning false once the params are consumed is what stops this looping: the
 * effect clears them, runs again, and finds nothing left to act on.
 */
export function shouldCaptureDeepLink(
  docParam: string | null,
  activeDocumentId: string | null,
  params: ParamReader,
): boolean {
  if (!docParam) return false
  if (docParam !== activeDocumentId) return true
  return hasDeepLinkParams(params)
}

/**
 * Where one arrival lands: a place inside the document it was captured for.
 *
 * Stamped with that document because the library holds it after the reader
 * closes. Unstamped, a note opened through `?note=` came back when the next
 * document was picked from the library, and that document opened on the other
 * document's note.
 */
export interface Arrival {
  documentId: string
  sectionId?: string
  chunkId?: string
  noteId?: string
  page?: number
  search?: string
  citationWords: string[]
}

export function readArrival(
  documentId: string,
  params: { get(name: string): string | null },
  citationWords: string[] = [],
): Arrival {
  const page = parseInt(params.get("page") ?? "", 10)
  return {
    documentId,
    sectionId: params.get("section_id") ?? undefined,
    chunkId: params.get("chunk_id") ?? undefined,
    noteId: params.get("note") ?? undefined,
    page: isNaN(page) ? undefined : page,
    search: params.get("search") ?? undefined,
    citationWords,
  }
}

/** The arrival that belongs to this document, or null when it belongs to another. */
export function arrivalFor(arrival: Arrival | null, documentId: string): Arrival | null {
  return arrival?.documentId === documentId ? arrival : null
}
