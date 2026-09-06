import { useEffect, useState } from "react"

import { readerLandingTab, type ReaderTab } from "./readerLandingTab"

export type { ReaderTab }

interface UseReaderTabsOpts {
  format: string | undefined
  hasDeepLink: boolean
  /** A section or chunk was named, which only the Read view can scroll to. */
  hasPassageLink?: boolean
}

// Owns the left-panel tab state and the lazy-mount visited flags. Format
// mismatches (e.g. user is on the pdfview tab but the document isn't a PDF)
// are corrected to the reader that format does have, never to the section list.
export function useReaderTabs({ format, hasDeepLink, hasPassageLink = false }: UseReaderTabsOpts) {
  // Derived, not latched. `format` is undefined on the first render because the
  // document is still loading, so latching the landing tab decided every document
  // as if it had no format: a cited PDF opened the extracted text instead of the
  // page, because the branch that would have sent it to the viewer never saw a
  // format to match. Deriving means the tab follows the format the moment it
  // arrives, and stops the moment the reader picks a tab themselves.
  const landingTab = readerLandingTab(format, hasDeepLink, hasPassageLink)
  const [chosenTab, setChosenTab] = useState<ReaderTab | null>(null)
  const requestedTab = chosenTab ?? landingTab
  // A tab the format cannot serve falls back to the reader every format has --
  // never to the section list. Derived rather than corrected in an effect, so
  // there is no frame showing a panel that is about to be replaced. `undefined`
  // means the document is still loading, which is not a mismatch.
  const formatMismatch =
    format !== undefined &&
    ((requestedTab === "pdfview" && format !== "pdf") ||
      (requestedTab === "bookview" && format !== "epub"))
  const leftTab = formatMismatch ? "read" : requestedTab
  const setLeftTab = setChosenTab
  const initialTab = landingTab
  // PDF View tab visited at least once -> mount and keep alive.
  const [pdfViewVisited, setPdfViewVisited] = useState(initialTab === "pdfview")
  // Book View tab visited at least once -> mount and keep alive.
  const [bookViewVisited, setBookViewVisited] = useState(initialTab === "bookview")

  // Latch the visited flags so a panel stays mounted once shown. The mismatch
  // correction that used to live here is derived above.
  useEffect(() => {
    if (leftTab === "pdfview") setPdfViewVisited(true)
    else if (leftTab === "bookview") setBookViewVisited(true)
  }, [leftTab])

  return {
    leftTab,
    setLeftTab,
    pdfViewVisited,
    setPdfViewVisited,
    bookViewVisited,
    setBookViewVisited,
  }
}
