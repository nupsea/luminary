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
  /** What the sheet is printed as, when the book numbers front matter apart. */
  pdf_page_label?: string | null
  section_preview_snippet: string // first 150 chars of chunk text
}

/**
 * How a citation's page should read to someone holding the book.
 *
 * A PDF's sheet position is not the page printed on it: measured on a 613-page
 * book, sheet 41 is printed "19", so a chip naming the sheet disagreed with the
 * reader's own eyes by twenty for the whole body. The label is display only --
 * the chip still navigates by sheet, which is what the viewer scrolls to.
 */
export function citationPageText(citation: SourceCitation): string {
  const label = (citation.pdf_page_label ?? "").trim()
  if (label) return ` p.${label}`
  return Number(citation.pdf_page_number) > 0 ? ` p.${citation.pdf_page_number}` : ""
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
