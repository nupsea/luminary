/**
 * Which page of a paginated document holds the cited passage.
 *
 * A citation does not always carry a page: `pdf_page_number` is null whenever
 * ingestion could not attribute the chunk to a sheet, and a viewer that opens at
 * page 1 and highlights only what is on screen then shows nothing at all. The
 * passage is the address; the page is derived from it.
 *
 * Kept free of pdf.js so it can be tested with a plain function: the caller
 * supplies "give me the text of page n", whatever that costs it.
 */

import { longestPresentRun } from "./match"

export interface LocatePageOptions {
  /** 1-based page count. */
  pageCount: number
  /** Text of one page, 1-based. */
  getPageText: (page: number) => Promise<string>
  /** Where to look first — the citation's own page, when it has one. */
  preferredPage?: number | null
  /** Abandon the scan; the reader has navigated away. */
  isCancelled?: () => boolean
}

/**
 * The first page whose text contains the passage, or null.
 *
 * The preferred page is tried first and separately, so a citation that does carry
 * a page costs one text extraction rather than a scan. Everything else is scanned
 * in reading order, which is also the order a reader would expect a first match.
 */
export async function locateCitationPage(
  words: string[],
  { pageCount, getPageText, preferredPage, isCancelled }: LocatePageOptions,
): Promise<number | null> {
  if (words.length === 0 || pageCount <= 0) return null

  const order: number[] = []
  if (preferredPage && preferredPage >= 1 && preferredPage <= pageCount) {
    order.push(preferredPage)
  }
  for (let p = 1; p <= pageCount; p++) if (p !== preferredPage) order.push(p)

  for (const page of order) {
    if (isCancelled?.()) return null
    let text = ""
    try {
      text = await getPageText(page)
    } catch {
      continue // a page that will not yield text is not a match, and not fatal
    }
    if (longestPresentRun(words, text).length > 0) return page
  }
  return null
}
