// Pure helpers for in-document search inside the Read view.
//
// Both exist because a search hit that cannot be seen reads as a search that
// does not work: one marks the term in the prose, the other makes sure the
// section holding it is actually rendered before anything tries to scroll to
// it.

// Distinct from the annotation palette: a search mark is transient UI, not
// something the reader saved, and the two appear together.
export const SEARCH_MARK_TOKEN = "luminary-search-mark"
export const SEARCH_MARK_CLASS =
  `bg-sky-200 text-sky-950 dark:bg-sky-700 dark:text-sky-50 rounded-sm px-0.5 ${SEARCH_MARK_TOKEN}`

export const SEARCH_ACTIVE_MARK_TOKEN = "luminary-search-active-mark"

/**
 * Update DOM classes to reflect the currently active search mark and return its details.
 */
export function setActiveSearchMark(
  container: HTMLElement,
  activeIndex: number,
): { activeEl: HTMLElement | null; total: number; sectionId: string | null } {
  const marks = Array.from(container.querySelectorAll<HTMLElement>(`.${SEARCH_MARK_TOKEN}`))
  const total = marks.length
  if (total === 0) return { activeEl: null, total: 0, sectionId: null }

  const clampedIndex = ((activeIndex % total) + total) % total
  let targetSectionId: string | null = null

  marks.forEach((el, idx) => {
    if (idx === clampedIndex) {
      el.classList.add(
        SEARCH_ACTIVE_MARK_TOKEN,
        "ring-2",
        "ring-amber-500",
        "bg-amber-300",
        "dark:bg-amber-400",
        "text-amber-950",
      )
      el.classList.remove("bg-sky-200", "dark:bg-sky-700", "text-sky-950", "dark:text-sky-50")
      const sec = el.closest<HTMLElement>("[id^='read-sec-']")
      if (sec) {
        targetSectionId = sec.id.replace("read-sec-", "")
      }
    } else {
      el.classList.remove(
        SEARCH_ACTIVE_MARK_TOKEN,
        "ring-2",
        "ring-amber-500",
        "bg-amber-300",
        "dark:bg-amber-400",
      )
      el.classList.add("bg-sky-200", "dark:bg-sky-700", "text-sky-950", "dark:text-sky-50")
    }
  })

  return {
    activeEl: marks[clampedIndex] ?? null,
    total,
    sectionId: targetSectionId,
  }
}

// One character matches nearly everything and turns the page into a sea of
// marks; two is the shortest term that still discriminates ("AI", "os").
const MIN_TERM_LENGTH = 2

function markNeedle(
  content: string,
  needle: string,
  className: string,
): { result: string; count: number } {
  const lower = content.toLowerCase()
  const lowerNeedle = needle.toLowerCase()
  let result = ""
  let cursor = 0
  let insideTag = false
  let i = 0
  let count = 0

  while (i < content.length) {
    const ch = content[i]
    if (ch === "<") insideTag = true
    else if (ch === ">") insideTag = false

    if (!insideTag && lower.startsWith(lowerNeedle, i)) {
      result += content.slice(cursor, i)
      result += `<mark class="${className}">${content.slice(i, i + needle.length)}</mark>`
      i += needle.length
      cursor = i
      count++
      continue
    }
    i++
  }
  return { result: result + content.slice(cursor), count }
}

/**
 * Wrap occurrences of `term` in <mark>, skipping anything inside an HTML tag.
 *
 * This runs on the output of `applyHighlights`, which has already injected
 * `<mark class="...">` for saved annotations -- matching inside one of those
 * class attributes would corrupt the markup, so the scan tracks whether it is
 * inside a tag and only marks body text.
 */
export function applySearchTerm(
  content: string,
  term: string,
  className: string = SEARCH_MARK_CLASS,
): string {
  const needle = term.trim()
  if (needle.length < MIN_TERM_LENGTH || !content) return content

  // First try the full exact term
  const exact = markNeedle(content, needle, className)
  if (exact.count > 0) return exact.result

  // If full term had no matches and contains multiple words, match individual words (>= 3 chars)
  const words = needle.split(/\s+/).filter((w) => w.length >= 3)
  if (words.length <= 1) return content

  let current = content
  const sortedWords = [...new Set(words)].sort((a, b) => b.length - a.length)
  for (const word of sortedWords) {
    current = markNeedle(current, word, className).result
  }
  return current
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

/** The slice of a document's sections the Read view renders: `[start, start + limit)`. */
export interface SectionWindow {
  start: number
  limit: number
}

/**
 * The render window that includes `targetIndex`.
 *
 * A citation, search hit or contents entry naming a section outside the window
 * has no element to scroll to, and the jump silently does nothing. Grows the
 * window when the target is within `max` of its start, so the sections being
 * read stay mounted; otherwise moves it to the target with a page above. The
 * window never exceeds `max`, which the server refuses beyond -- only growing
 * from 0 left every section past the 200th unreachable.
 */
export function windowIncluding(
  win: SectionWindow,
  targetIndex: number,
  page: number,
  max: number,
): SectionWindow {
  if (targetIndex < 0) return win
  if (targetIndex >= win.start && targetIndex < win.start + win.limit) return win
  if (targetIndex >= win.start && targetIndex - win.start < max) {
    const needed = Math.ceil((targetIndex - win.start + 1) / page) * page
    return { start: win.start, limit: Math.min(Math.max(needed, win.limit), max) }
  }
  const start = Math.max(0, Math.floor(targetIndex / page) * page - page)
  return { start, limit: Math.min(targetIndex - start + page, max) }
}

/** One page further down; past `max` the window slides rather than grows. */
export function extendWindowDown(win: SectionWindow, page: number, max: number): SectionWindow {
  const limit = win.limit + page
  return limit <= max ? { start: win.start, limit } : { start: win.start + limit - max, limit: max }
}

/** One page further up, trimming the tail to stay within `max`. */
export function extendWindowUp(win: SectionWindow, page: number, max: number): SectionWindow {
  const start = Math.max(0, win.start - page)
  return { start, limit: Math.min(win.limit + win.start - start, max) }
}
