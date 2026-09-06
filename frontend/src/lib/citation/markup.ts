/** Marking a cited passage inside rendered HTML. */

import { wordsPattern } from "./match"

/** Stable token to query and scroll to; the colour classes beside it may change. */
export const CITATION_MARK_TOKEN = "luminary-citation-mark"

/** Deliberately not the search mark's colour: both can be on screen at once. */
export const CITATION_MARK_CLASS =
  `${CITATION_MARK_TOKEN} bg-amber-200 text-amber-950 dark:bg-amber-500/40 ` +
  "dark:text-amber-50 rounded-sm px-0.5"

/** Overlay fill for the PDF viewer, which draws rects rather than wrapping text. */
export const CITATION_OVERLAY_COLOR = "rgba(251, 191, 36, 0.45)"
export const CITATION_OVERLAY_ATTR = "data-citation-highlight"

/**
 * Wrap `words` where they occur in `content`, tolerating any whitespace between.
 *
 * A match containing a tag is skipped rather than wrapped: saved annotations are
 * already `<mark>` elements in this HTML, and splitting one corrupts the markup.
 */
export function markWords(content: string, words: string[], className: string): string {
  if (words.length === 0 || !content) return content
  return content.replace(wordsPattern(words, "gi"), (match) =>
    match.includes("<") || match.includes(">")
      ? match
      : `<mark class="${className}">${match}</mark>`,
  )
}
