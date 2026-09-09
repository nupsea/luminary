/** Turning a citation into something every view can locate. */

import { longestPresentRun, normalise } from "./match"
import type { CitationSource, CitationTarget } from "./types"

/**
 * Drop a leading title or heading the snippet carries but the prose does not.
 *
 * Compared after whitespace collapse and case-insensitively, because the chunk's
 * header is assembled separately from the body it precedes.
 */
export function stripCitationPrefixes(
  snippet: string,
  prefixes: (string | null | undefined)[],
): string {
  let out = normalise(snippet)
  for (const raw of prefixes) {
    const prefix = normalise(raw)
    if (prefix.length > 0 && out.toLowerCase().startsWith(prefix.toLowerCase())) {
      out = out.slice(prefix.length).trim()
    }
  }
  return out
}

/** Everything a view might use to locate this citation. */
export function buildCitationTarget(source: CitationSource): CitationTarget {
  const stripped = stripCitationPrefixes(source.section_preview_snippet ?? "", [
    source.document_title,
    source.section_heading,
  ])
  return {
    documentId: source.document_id ?? null,
    chunkId: source.chunk_id ?? null,
    sectionId: source.section_id ?? null,
    page: source.pdf_page_number ?? null,
    words: stripped ? stripped.split(" ").filter(Boolean) : [],
  }
}

/** The words of this target that `text` actually contains, or none. */
export function wordsPresentIn(target: Pick<CitationTarget, "words">, text: string): string[] {
  return target.words.length === 0 ? [] : longestPresentRun(target.words, text)
}

/**
 * Serialised for router state. Only the words travel as a string: ids and page
 * ride in the URL already, and a shared link should not reproduce a display hint.
 */
export function targetToStateValue(target: CitationTarget): string {
  return target.words.join(" ")
}

export function stateValueToWords(value: string | null | undefined): string[] {
  return normalise(value).split(" ").filter(Boolean)
}
