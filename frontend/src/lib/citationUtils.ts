/**
 * Pure citation helpers, kept out of SourceCitationChips.tsx so the component
 * file exports only components (fast refresh).
 */

import { formatLocus, locusOf } from "./citation/locus"

export interface SourceCitation {
  chunk_id: string
  document_id: string
  document_title: string
  section_id: string | null
  section_heading: string
  pdf_page_number: number | null
  /** What the sheet is printed as, when the book numbers front matter apart. */
  pdf_page_label?: string | null
  section_preview_snippet: string // first 150 chars of chunk text
  /** Seconds into a recording. Null for everything that is not one. */
  start_time?: number | null
}

/**
 * Where the citation points, as its chip shows it.
 *
 * A page is only one of the answers: a recording points at a moment and a source
 * file at a line, and naming a page for those is a claim the source cannot
 * support. `locusOf` picks the one this source has and returns null when it has
 * none -- see `lib/citation/locus`.
 */
export function citationLocusText(citation: SourceCitation): string {
  const text = formatLocus(
    locusOf({
      startTime: citation.start_time,
      page: citation.pdf_page_number,
      pageLabel: citation.pdf_page_label,
      heading: null,
    }),
  )
  return text ? ` ${text}` : ""
}

/**
 * Client-side deduplication by section_id.  When section_id is null, the
 * chunk_id is used as the dedup key (each unlinked chunk stays distinct).
 * Backend already deduplicates — this is a defensive second pass.
 */
export function deduplicateCitations(citations: SourceCitation[]): SourceCitation[] {
  const seen = new Set<string>()
  return citations.filter((c) => {
    const key = c.section_id ?? c.chunk_id
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}
