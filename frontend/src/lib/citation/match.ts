/**
 * Finding a cited passage inside text that does not match it character for
 * character.
 *
 * Three differences are routine and all three were seen in real citations:
 *
 *   1. Whitespace. The stored chunk collapses paragraph breaks, so a snippet
 *      reads "traps? GUEST: Two" where the prose holds "traps?\n\nGUEST: Two".
 *   2. Leading material. A chunk is stored with a breadcrumb or speaker header
 *      the prose never contains: "[Doc > Section] We experimented...".
 *   3. A fixed-length cut. The snippet ends mid-word, or runs past the passage.
 *
 * So matching works on words, slides both ends, and reports its result as words
 * rather than a string -- the caller has to locate them in raw text whose spacing
 * differs.
 */

/** Below this a match lands on any sentence and points the reader at the wrong place. */
export const MIN_MATCH_CHARS = 24

export function normalise(text: string | null | undefined): string {
  return (text ?? "").replace(/\s+/g, " ").trim()
}

/**
 * Whether `candidate` occurs in `hay` ending at a word boundary.
 *
 * Splitting into words is not enough on its own: a trailing fragment can still be
 * a substring of a longer word. "of the thr" is contained in "of the three
 * options", so a plain `includes` accepts it and a highlight stops mid-word.
 * Every occurrence is checked, because the first may fall inside a word where a
 * later one does not.
 */
export function endsOnWordBoundary(candidate: string, hay: string): boolean {
  let from = 0
  for (;;) {
    const at = hay.indexOf(candidate, from)
    if (at === -1) return false
    const after = hay[at + candidate.length]
    if (after === undefined || /\W/.test(after)) return true
    from = at + 1
  }
}

/** The longest contiguous run of `words` present in `text`, as words. */
export function longestPresentRun(words: string[], text: string): string[] {
  const hay = normalise(text).toLowerCase()
  let best: string[] = []
  for (let start = 0; start < words.length; start++) {
    if (words.slice(start).join(" ").length < MIN_MATCH_CHARS) break
    for (let end = words.length; end > start; end--) {
      const candidate = words.slice(start, end)
      const text_ = candidate.join(" ")
      if (text_.length < MIN_MATCH_CHARS) break
      if (endsOnWordBoundary(text_.toLowerCase(), hay)) {
        if (text_.length > best.join(" ").length) best = candidate
        break
      }
    }
  }
  return best
}

export function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

/** A regex matching `words` with any whitespace run between them. */
export function wordsPattern(words: string[], flags = "i"): RegExp {
  return new RegExp(words.map(escapeRegExp).join("\\s+"), flags)
}

/**
 * Character offsets of `words` within `text`, or null.
 *
 * For callers that address text by offset rather than by markup -- the PDF text
 * layer measures a range between two indices in its concatenated span text.
 */
export function findRunOffsets(
  text: string,
  words: string[],
): { start: number; end: number } | null {
  if (words.length === 0 || !text) return null
  const match = wordsPattern(words, "i").exec(text)
  return match ? { start: match.index, end: match.index + match[0].length } : null
}
