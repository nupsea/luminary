export type ReaderTab = "sections" | "pdfview" | "bookview" | "read"

/**
 * The tab a document opens on.
 *
 * Sections is a table of contents, not a reader: landing there means a
 * document opens on a list of its own headings and the prose is one more
 * click away. PDF and EPUB have dedicated viewers, and a deep link names a
 * passage the Read view can scroll to, so every other format — html, md,
 * docx, txt, media transcripts — reads in the universal reader.
 */
export function readerLandingTab(format: string | undefined, hasDeepLink: boolean): ReaderTab {
  if (format === "pdf") return "pdfview"
  if (hasDeepLink) return "read"
  if (format === "epub") return "bookview"
  return "read"
}
