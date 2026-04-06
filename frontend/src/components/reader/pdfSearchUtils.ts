/**
 * Pure utility functions for PDF text search -- testable in Vitest node env.
 * No DOM, React, or pdfjs imports.
 */

export interface PageMatch {
  page: number
  /** Character index within the page text where the match starts */
  index: number
}

/**
 * Find all case-insensitive occurrences of `query` in `text`.
 * Returns an array of start indices.
 */
export function findMatchIndices(text: string, query: string): number[] {
  if (!query) return []
  const lowerText = text.toLowerCase()
  const lowerQuery = query.toLowerCase()
  const indices: number[] = []
  let pos = 0
  while (pos <= lowerText.length - lowerQuery.length) {
    const idx = lowerText.indexOf(lowerQuery, pos)
    if (idx < 0) break
    indices.push(idx)
    pos = idx + 1
  }
  return indices
}

/**
 * Build a global match list from a page text cache.
 * Pages are sorted numerically. Returns (page, index) pairs.
 */
export function buildGlobalMatches(
  pageTextCache: Map<number, string>,
  query: string,
): PageMatch[] {
  if (!query) return []
  const pages = Array.from(pageTextCache.keys()).sort((a, b) => a - b)
  const matches: PageMatch[] = []
  for (const page of pages) {
    const text = pageTextCache.get(page) ?? ""
    const indices = findMatchIndices(text, query)
    for (const index of indices) {
      matches.push({ page, index })
    }
  }
  return matches
}

/**
 * Given a global match index and the current page, count matches on the current page
 * and compute the "X of Y on page" display string.
 */
export function formatMatchCounts(
  globalMatches: PageMatch[],
  globalIndex: number,
  currentPage: number,
): { pageCount: number; totalCount: number; pageIndex: number; label: string } {
  const totalCount = globalMatches.length
  const pageMatches = globalMatches.filter(m => m.page === currentPage)
  const pageCount = pageMatches.length

  // Find which page-local match the current global index corresponds to
  let pageIndex = -1
  if (globalIndex >= 0 && globalIndex < totalCount) {
    const current = globalMatches[globalIndex]
    if (current.page === currentPage) {
      pageIndex = pageMatches.findIndex(
        m => m.index === current.index,
      )
    }
  }

  if (totalCount === 0) return { pageCount: 0, totalCount: 0, pageIndex: -1, label: "No matches" }

  const pageLabel = pageIndex >= 0
    ? `${pageIndex + 1} of ${pageCount} on page`
    : `${pageCount} on page`

  return {
    pageCount,
    totalCount,
    pageIndex,
    label: `${pageLabel}, ${totalCount} total`,
  }
}
