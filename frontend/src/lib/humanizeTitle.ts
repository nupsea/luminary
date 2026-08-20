// Words that stay lowercase inside a title, but not as its first word.
const SMALL_WORDS = new Set([
  "a",
  "an",
  "and",
  "as",
  "at",
  "but",
  "by",
  "for",
  "from",
  "in",
  "of",
  "on",
  "or",
  "the",
  "to",
  "vs",
  "with",
])

const EXTENSIONS = /\.(pdf|epub|docx?|txt|md|mp3|m4a|wav|mp4|html?)$/i

// A short token with no vowel in it is an acronym, not a word. Measured on one
// library: `sutton_barto_rl`, `matrix_calculus_for_dl` and `radiology_chexnet_cxr`
// read as "Rl", "Dl" and "Cxr" without this. `y` counts as a vowel so a title
// opening with "by" is a word; `ddia` has vowels and stays "Ddia", because a
// lowercase four-letter token with vowels cannot be told from a word.
const ACRONYM = /^[^aeiouy]{2,4}$/i

/**
 * A stored title rendered for reading.
 *
 * Two thirds of one library's titles are the filename the document arrived as
 * -- `art_of_unix`, `sherlock_holmes`, `retrieval-and-memory-tutorial` -- because
 * that is what the source gave us and inventing a better one would be inventing.
 * This changes presentation only: the stored title is what search, citations and
 * exports use, and callers show it on hover.
 *
 * A title that already reads as a title is left exactly as it is. So is any word
 * carrying its own capitals, so `DDIA` does not become `Ddia`.
 */
export function humanizeTitle(title: string): string {
  const trimmed = title.trim()
  if (!trimmed) return trimmed
  // Already prose: spaces mean a human or a parser wrote this.
  if (/\s/.test(trimmed)) return trimmed

  const withoutExtension = trimmed.replace(EXTENSIONS, "")
  const words = withoutExtension.split(/[_-]+/).filter(Boolean)
  if (words.length === 0) return trimmed

  return words
    .map((word, i) => {
      // The author's own capitals are information: acronyms, camelCase, `iPhone`.
      if (/[A-Z]/.test(word)) return word
      if (i > 0 && SMALL_WORDS.has(word.toLowerCase())) return word.toLowerCase()
      if (ACRONYM.test(word.replace(/[0-9]/g, ""))) return word.toUpperCase()
      return word.charAt(0).toUpperCase() + word.slice(1)
    })
    .join(" ")
}
