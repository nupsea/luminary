// Pure helpers for in-document search inside the Read view.
//
// Both exist because a search hit that cannot be seen reads as a search that
// does not work: one marks the term in the prose, the other makes sure the
// section holding it is actually rendered before anything tries to scroll to
// it.

// Distinct from the annotation palette: a search mark is transient UI, not
// something the reader saved, and the two appear together.
export const SEARCH_MARK_CLASS =
  "bg-sky-200 text-sky-950 dark:bg-sky-700 dark:text-sky-50 rounded-sm px-0.5"

// One character matches nearly everything and turns the page into a sea of
// marks; two is the shortest term that still discriminates ("AI", "os").
const MIN_TERM_LENGTH = 2

/**
 * Wrap occurrences of `term` in <mark>, skipping anything inside an HTML tag.
 *
 * This runs on the output of `applyHighlights`, which has already injected
 * `<mark class="...">` for saved annotations -- matching inside one of those
 * class attributes would corrupt the markup, so the scan tracks whether it is
 * inside a tag and only marks body text.
 */
export function applySearchTerm(content: string, term: string): string {
  const needle = term.trim()
  if (needle.length < MIN_TERM_LENGTH || !content) return content

  const lower = content.toLowerCase()
  const lowerNeedle = needle.toLowerCase()
  let result = ""
  let cursor = 0
  let insideTag = false
  let i = 0

  while (i < content.length) {
    const ch = content[i]
    if (ch === "<") insideTag = true
    else if (ch === ">") insideTag = false

    if (!insideTag && lower.startsWith(lowerNeedle, i)) {
      result += content.slice(cursor, i)
      result += `<mark class="${SEARCH_MARK_CLASS}">${content.slice(i, i + needle.length)}</mark>`
      i += needle.length
      cursor = i
      continue
    }
    i++
  }
  return result + content.slice(cursor)
}

/**
 * Put search hits in reading order.
 *
 * `GET /documents/{id}/search` ranks by relevance, which is right for a result
 * list and wrong for the reader's next/previous controls: stepping forward
 * walked the document backwards (measured on one document: sections 20, 14,
 * 10, 11, 25...). Cmd+F means "the next one below where I am", so the reader
 * sorts by position. A hit whose section is not in the order map sorts last
 * rather than being dropped -- it is still a real match.
 */
export function orderHitsByDocument<T extends { section_id: string }>(
  hits: T[],
  sectionOrder: Map<string, number>,
): T[] {
  const rank = (h: T) => sectionOrder.get(h.section_id) ?? Number.MAX_SAFE_INTEGER
  return [...hits].sort((a, b) => rank(a) - rank(b))
}

/**
 * The render window needed to include `targetIndex`, given the current one.
 *
 * The Read view renders a page of sections at a time and otherwise grows only
 * as the reader scrolls, so a search hit (or a deep link) naming a section
 * past the window has no element to scroll to and the jump silently does
 * nothing. Never shrinks the window -- that would unmount sections the reader
 * is looking at -- and never exceeds `max`, which the server refuses beyond.
 */
export function widenedListLimit(
  currentLimit: number,
  targetIndex: number,
  page: number,
  max: number,
): number {
  if (targetIndex < 0 || targetIndex < currentLimit) return currentLimit
  const needed = Math.ceil((targetIndex + 1) / page) * page
  return Math.min(Math.max(needed, currentLimit), max)
}
