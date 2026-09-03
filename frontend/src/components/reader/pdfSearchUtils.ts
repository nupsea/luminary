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

/** What the reader typed into the page field.
 *
 * `19` is sheet 19, unchanged. `p19` and `p.xiv` name the number *printed* on
 * the page, which is what the footer chip, the contents list and every citation
 * report -- the field was the only surface with no way to accept one.
 *
 * The prefix is required rather than inferred: on a book with front matter,
 * `19` is a valid sheet and a valid printed page at once, and guessing would
 * silently move where a typed number lands.
 */
export function parsePageEntry(
  raw: string,
): { kind: "sheet"; sheet: number } | { kind: "printed"; label: string } | null {
  const text = (raw ?? "").trim()
  if (!text) return null
  const printed = /^p\.?\s*(.+)$/i.exec(text)
  if (printed) {
    const label = printed[1].trim()
    return label ? { kind: "printed", label } : null
  }
  if (!/^\d+$/.test(text)) return null
  return { kind: "sheet", sheet: parseInt(text, 10) }
}

/** The sheet carrying this printed label, or null if no page is printed with it.
 *
 * Both label sources are consulted because they disagree in coverage: the PDF's
 * own declared labels are absent from many files, and the ingestion-derived map
 * only covers documents where enough pages agreed on one offset.
 *
 * Case-insensitive so `p.XIV` finds a page printed `xiv`.
 */
export function sheetForPrintedLabel(
  declared: string[] | null | undefined,
  derived: Record<string, string> | null | undefined,
  label: string,
): number | null {
  const wanted = label.trim().toLowerCase()
  if (!wanted) return null

  for (const [sheet, value] of Object.entries(derived ?? {})) {
    if (String(value).trim().toLowerCase() === wanted) {
      const n = parseInt(sheet, 10)
      if (!isNaN(n)) return n
    }
  }
  if (declared) {
    for (let i = 0; i < declared.length; i++) {
      if ((declared[i] ?? "").trim().toLowerCase() === wanted) return i + 1
    }
  }
  return null
}

// The ladder the +/- buttons walk. Steps rather than a linear slider because a
// fixed increment is coarse at 50% and useless at 300%; these are the stops
// every PDF reader offers. Auto-fit can land between or above them, which is
// why stepping searches for the neighbouring stop rather than adding a delta.
export const ZOOM_STOPS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3, 4]

// Offered by name in the menu. Fit width and fit page are computed from the
// page, so they are not in this list.
export const ZOOM_PRESETS = [0.5, 0.75, 1, 1.25, 1.5, 2]

export function stepZoom(current: number, direction: 1 | -1): number {
  if (direction > 0) {
    return ZOOM_STOPS.find((stop) => stop > current + 0.001) ?? ZOOM_STOPS[ZOOM_STOPS.length - 1]
  }
  const below = ZOOM_STOPS.filter((stop) => stop < current - 0.001)
  return below.length ? below[below.length - 1] : ZOOM_STOPS[0]
}

