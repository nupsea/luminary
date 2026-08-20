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

/**
 * Index of the active match *within the current page*, or -1 when the active
 * match is on another page.
 *
 * Pulled out as a pure function so the highlight effect can depend on a number
 * rather than on the identity of the match array. Progressive extraction
 * replaces that array once per ten-page batch -- 62 times on a 600-page book --
 * and the effect clears every overlay before redrawing it. The redraw is
 * identical each time; the clear is what the reader sees as flicker.
 */
export function activeMatchIndexForPage(
  matches: PageMatch[],
  globalMatchIndex: number,
  page: number,
): number {
  if (globalMatchIndex < 0 || globalMatchIndex >= matches.length) return -1
  const current = matches[globalMatchIndex]
  if (current.page !== page) return -1
  let local = 0
  for (const match of matches) {
    if (match.page !== page) continue
    if (match.index === current.index) return local
    local += 1
  }
  return -1
}

/**
 * The page number printed on the sheet, when the PDF says it differs from the
 * sheet's position in the file.
 *
 * A book's front matter is numbered separately, so a PDF carries page *labels*
 * alongside page indices: measured on one 613-page book, sheet 41 is printed
 * "19" and sheet 6 is printed "iv". The viewer counted sheets, so its footer
 * disagreed with the page in the reader's hands by twenty for the whole body.
 *
 * Returns null when the label adds nothing -- either the PDF defines none, or
 * it is the sheet number already -- so the footer stays uncluttered on the
 * documents where counting sheets is the right answer.
 */
export function printedPageLabel(
  labels: string[] | null | undefined,
  page: number,
): string | null {
  if (!labels || page < 1 || page > labels.length) return null
  const label = (labels[page - 1] ?? "").trim()
  if (!label || label === String(page)) return null
  return label
}
