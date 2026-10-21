// A place in an EPUB: the chapter, and the block (paragraph, list item, figure)
// inside it. A chapter can run to 20,000 words, so the chapter alone does not say
// where reading stopped. Blocks are counted in document order, which layout,
// zoom and late-loading images do not change.

export interface EpubPlace {
  chapter: number
  block: number
}

export const EPUB_BLOCK_SELECTOR =
  "p, li, dt, dd, pre, figure, table, blockquote, h1, h2, h3, h4, h5, h6, div[data-type='equation']"

/** Pixels below the top of the reading pane that still count as "at the top". */
export const READING_LINE_PX = 16

/**
 * The block being read: the last one whose top is at or above the reading line.
 * Tops rise with document order, so this is a binary search.
 */
export function blockAtLine(count: number, topOf: (i: number) => number, line: number): number {
  let lo = 0
  let hi = count - 1
  let found = 0
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (topOf(mid) <= line) {
      found = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return found
}

/** A place from the saved position's columns; a missing block is the chapter's start. */
export function epubPlaceOf(
  chapter: number | null | undefined,
  block: number | null | undefined,
): EpubPlace | null {
  return chapter == null ? null : { chapter, block: block ?? 0 }
}

export function samePlace(a: EpubPlace | null | undefined, b: EpubPlace | null | undefined): boolean {
  return a != null && b != null && a.chapter === b.chapter && a.block === b.block
}
