export type ReaderTab = "sections" | "pdfview" | "bookview" | "read"

/**
 * The tab a document opens on.
 *
 * Sections is a table of contents, not a reader: landing there means a document
 * opens on a list of its own headings and the prose is one more click away. PDF
 * and EPUB have dedicated viewers, so that is where they open.
 *
 * **A named passage overrides the format.** A citation carries a section or a
 * chunk, and only the Read view can scroll to one and mark it. A PDF used to win
 * that contest, so arriving from a citation opened the PDF viewer while the Read
 * view scrolled to the passage behind it, hidden -- sections render only when
 * visible, so the cited text was never even in the DOM and nothing was marked.
 *
 * A *page* is not a passage. It means something in the PDF viewer and nothing in
 * the Read view, so a page-only deep link still lands on the PDF.
 */
export function readerLandingTab(
  format: string | undefined,
  hasDeepLink: boolean,
  hasPassageLink: boolean = false,
): ReaderTab {
  if (hasPassageLink) return "read"
  if (format === "pdf") return "pdfview"
  if (hasDeepLink) return "read"
  if (format === "epub") return "bookview"
  return "read"
}
