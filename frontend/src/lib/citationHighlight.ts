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
 * The longest leading run of `needle` that occurs in `haystack`, or "".
 *
 * Trimmed back to a word boundary so a highlight never ends mid-word, and
 * shortened a word at a time rather than a character at a time — a citation that
 * matches for 80 of its 150 characters should highlight those 80.
 */
export function longestPresentPrefix(needle: string, haystack: string): string {
  const words = normalise(needle).split(" ").filter(Boolean)
  const hay = normalise(haystack).toLowerCase()
  for (let count = words.length; count > 0; count--) {
    const candidate = words.slice(0, count).join(" ")
    if (candidate.length < MIN_NEEDLE_LENGTH) return ""
    if (endsOnWordBoundary(candidate.toLowerCase(), hay)) return candidate
  }
  return ""
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

/** How long the mark stays up. Long enough to find by eye, short enough not to persist. */
export const CITATION_HIGHLIGHT_MS = 6_000

// Deliberately not the search mark's colour: a reader who arrived from a citation
// and a reader who is searching are looking for different things, and the two can
// be on screen at once.
/** Stable token to scroll to; the colour classes beside it are free to change. */
export const CITATION_MARK_TOKEN = "luminary-citation-mark"

export const CITATION_MARK_CLASS =
  `${CITATION_MARK_TOKEN} bg-amber-200 text-amber-950 dark:bg-amber-500/40 ` +
  "dark:text-amber-50 rounded-sm px-0.5"
