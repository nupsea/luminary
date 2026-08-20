/**
 * What the Study page is scoped to: a collection, one document, or neither.
 *
 * "Neither" is the landing page — the due-review call to action, the session
 * manager and the collection grid — and it was unreachable. The effective
 * document hook falls back to the last-read document so every learning surface
 * has something to render; on Study that turned "open Study" into "reopen
 * whatever I read last", and clearing the selection from the heading put it
 * straight back, because clearing is exactly what makes the fallback apply.
 *
 * So the *open* document is the one the user chose (`rawActiveId`), while the
 * *rendered* one stays `effectiveDocumentId` — a choice that is still
 * ingesting keeps falling back to a readable document with its banner.
 */
export function studyScopeDocumentId(
  activeCollectionId: string | null,
  rawActiveId: string | null,
  effectiveDocumentId: string | null,
): string | null {
  // A collection scope must not mix a stale document into the session.
  if (activeCollectionId) return null
  if (rawActiveId === null) return null
  return effectiveDocumentId
}
