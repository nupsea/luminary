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
export const DEEP_LINK_PARAMS = ["section_id", "chunk_id", "page", "search"] as const

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
