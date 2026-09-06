/**
 * What a citation is, and what a view needs to show it.
 *
 * `CitationSource` is what the API hands us. `CitationTarget` is what every view
 * consumes: ids for the views that can address a passage exactly, and words for
 * the views that have to find it in text. Keeping them apart is the point -- a
 * transcript needs only the chunk id, a PDF needs only the words and the page,
 * and neither should have to know how the other locates anything.
 */

/** A source citation as the answer stream returns it. */
export interface CitationSource {
  chunk_id?: string | null
  document_id?: string | null
  document_title?: string | null
  section_id?: string | null
  section_heading?: string | null
  pdf_page_number?: number | null
  section_preview_snippet?: string | null
}

/** A citation resolved into everything a view might use to locate it. */
export interface CitationTarget {
  documentId: string | null
  /** Exact address, for views that render one element per chunk. */
  chunkId: string | null
  /** Exact address, for views that render one element per section. */
  sectionId: string | null
  /** Sheet number, for the PDF viewer. */
  page: number | null
  /**
   * The passage as words, for views that must find it in rendered text.
   *
   * Words rather than a string because the text they are matched against differs
   * in whitespace from the stored chunk: prose keeps the paragraph breaks the
   * chunk collapsed, and a PDF text layer joins its spans with single spaces.
   */
  words: string[]
}
