/**
 * Pure citation helpers, kept out of SourceCitationChips.tsx so the component
 * file exports only components (fast refresh).
 */

export interface SourceCitation {
  chunk_id: string
  document_id: string
  document_title: string
  section_id: string | null
  section_heading: string
  pdf_page_number: number | null
  section_preview_snippet: string // first 150 chars of chunk text
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
