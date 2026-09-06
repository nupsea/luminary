// Turning a citation chip's snippet into something findable in the rendered prose.
//
// A chip carries `section_preview_snippet` — the opening of the chunk the answer
// was generated from — and clicking it opens the reader at that section. Landing
// on the right section is not the same as showing which words were the source:
// the reader still has to find them, which is the thing the chip was supposed to
// settle.
//
// Two reasons a naive substring search fails, both seen in real citations:
//
//   1. The snippet is prefixed with the document title and section heading, which
//      the prose does not repeat at that point.
//   2. It is cut at a fixed length, so it can end mid-word.
//
// So the needle is stripped of those prefixes and then shortened until it is
// actually present. Matching nothing is a normal outcome — the prose is what the
// source authored (I-29), and a chunk boundary need not fall on one.

/** Shorter than this and a match says nothing; it would land on any sentence. */
const MIN_NEEDLE_LENGTH = 24

/** Whitespace differences between stored chunk text and rendered prose are noise. */
function normalise(text: string): string {
  return text.replace(/\s+/g, " ").trim()
}

/**
 * Drop a leading title/heading the snippet carries but the prose does not.
 *
 * Compared case-insensitively and after whitespace collapse, because the chunk
 * header is assembled separately from the body it precedes.
 */
export function stripCitationPrefixes(
  snippet: string,
  prefixes: (string | null | undefined)[],
): string {
  let out = normalise(snippet)
  for (const raw of prefixes) {
    const prefix = normalise(raw ?? "")
    if (prefix.length > 0 && out.toLowerCase().startsWith(prefix.toLowerCase())) {
      out = out.slice(prefix.length).trim()
    }
  }
  return out
}

/**
 * The longest contiguous run of snippet words present in `haystack`, as words.
 *
 * Both ends slide. The end must, because the snippet is cut at a fixed length and
 * can run past the passage. The **start** must too, and that is not obvious: a
 * chunk's stored text is prefixed with material the prose does not contain -- a
 * breadcrumb like `[Doc > Section]`, or speaker labels -- so a matcher that only
 * trims the tail keeps that prefix and finds nothing. Measured against a real
 * citation: prefix-only found no match where sliding found 53 characters.
 *
 * Returns the words, not a string, because the caller has to match them against
 * raw text whose whitespace differs (see `markWords`).
 */
export function longestPresentRun(needle: string, haystack: string): string[] {
  const words = normalise(needle).split(" ").filter(Boolean)
  const hay = normalise(haystack).toLowerCase()
  let best: string[] = []
  for (let start = 0; start < words.length; start++) {
    if (words.slice(start).join(" ").length < MIN_NEEDLE_LENGTH) break
    for (let end = words.length; end > start; end--) {
      const candidate = words.slice(start, end)
      const text = candidate.join(" ")
      if (text.length < MIN_NEEDLE_LENGTH) break
      if (endsOnWordBoundary(text.toLowerCase(), hay)) {
        if (text.length > best.join(" ").length) best = candidate
        break
      }
    }
  }
  return best
}

/**
 * Whether `candidate` occurs in `hay` ending at a word boundary.
 *
 * Splitting the needle into words is not enough on its own: a trailing fragment
 * can still be a substring of a longer word in the prose. "…of the thr" is
 * contained in "…of the three options", so a plain `includes` accepts it and the
 * highlight stops mid-word. Every occurrence is checked, because the first one
 * may fall inside a word while a later one does not.
 */
function endsOnWordBoundary(candidate: string, hay: string): boolean {
  let from = 0
  for (;;) {
    const at = hay.indexOf(candidate, from)
    if (at === -1) return false
    const after = hay[at + candidate.length]
    if (after === undefined || /\W/.test(after)) return true
    from = at + 1
  }
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

/**
 * Wrap `words` where they occur in `content`, tolerating any whitespace between.
 *
 * The stored chunk text collapses the paragraph breaks the prose actually
 * contains: a snippet reads "traps? GUEST: Two big ones" where the section holds
 * "traps?\n\nGUEST: Two big ones". Matching the normalised string against the raw
 * body therefore finds nothing, which is why the mark silently never appeared on
 * any document whose passage crossed a paragraph.
 *
 * A match containing a tag is skipped rather than wrapped -- `applyHighlights` may
 * already have inserted `<mark>` for a saved annotation, and splitting one would
 * corrupt the markup.
 */
export function markWords(content: string, words: string[], className: string): string {
  if (words.length === 0 || !content) return content
  const pattern = new RegExp(words.map(escapeRegExp).join("\\s+"), "gi")
  return content.replace(pattern, (match) =>
    match.includes("<") || match.includes(">")
      ? match
      : `<mark class="${className}">${match}</mark>`,
  )
}

export interface CitationLike {
  section_preview_snippet?: string | null
  document_title?: string | null
  section_heading?: string | null
}

/** What to look for in the prose for this citation, or "" when there is nothing usable. */
export function citationNeedle(citation: CitationLike): string {
  const snippet = citation.section_preview_snippet ?? ""
  if (!snippet.trim()) return ""
  return stripCitationPrefixes(snippet, [citation.document_title, citation.section_heading])
}

// Deliberately not the search mark's colour: a reader who arrived from a citation
// and a reader who is searching are looking for different things, and the two can
// be on screen at once.
/** Stable token to scroll to; the colour classes beside it are free to change. */
export const CITATION_MARK_TOKEN = "luminary-citation-mark"

export const CITATION_MARK_CLASS =
  `${CITATION_MARK_TOKEN} bg-amber-200 text-amber-950 dark:bg-amber-500/40 ` +
  "dark:text-amber-50 rounded-sm px-0.5"
