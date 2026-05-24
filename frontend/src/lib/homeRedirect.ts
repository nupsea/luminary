// Legacy deep-link params that used to land on / (the old Library route).
// Per redesign-phase-2-plan 2E.0, these forward to /library with the same
// query string so old bookmarks, in-app links, and notes citations keep working.
const LEGACY_LIBRARY_PARAMS = ["doc", "section_id", "chunk_id", "page", "tag"] as const

export function getHomeRedirectTarget(search: string): string | null {
  if (!search) return null
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search)
  const hasLegacy = LEGACY_LIBRARY_PARAMS.some((k) => params.has(k))
  if (!hasLegacy) return null
  const qs = search.startsWith("?") ? search : `?${search}`
  return `/library${qs}`
}
