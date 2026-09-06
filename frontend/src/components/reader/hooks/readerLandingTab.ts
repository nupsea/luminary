export type ReaderTab = "sections" | "pdfview" | "bookview" | "read"

/**
 * The tab a document opens on.
 *
 * Sections is a table of contents, not a reader: landing there means a document
 * opens on a list of its own headings and the prose is one more click away.
 *
 * **A PDF opens in the PDF viewer, citation or not.** It renders the source
 * itself and draws the cited passage on the page, so sending a citation to the
 * extracted text instead would show the reader a transcription of what they asked
 * to see. An EPUB has no such overlay, so a named passage goes to the Read view,
 * which can scroll to it and mark it.
 *
 * A *page* is not a passage either way: it means something in the PDF viewer and
 * nothing in the Read view.
 */
export function readerLandingTab(
  format: string | undefined,
  hasDeepLink: boolean,
  hasPassageLink: boolean = false,
): ReaderTab {
  if (format === "pdf") return "pdfview"
  if (hasPassageLink || hasDeepLink) return "read"
  if (format === "epub") return "bookview"
  return "read"
}
