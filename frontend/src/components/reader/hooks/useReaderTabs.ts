import { useEffect, useState } from "react"

import { readerLandingTab, type ReaderTab } from "./readerLandingTab"

export type { ReaderTab }

interface UseReaderTabsOpts {
  format: string | undefined
  hasDeepLink: boolean
}

// Owns the left-panel tab state and the lazy-mount visited flags. Format
// mismatches (e.g. user is on the pdfview tab but the document isn't a PDF)
// are corrected to the reader that format does have, never to the section list.
export function useReaderTabs({ format, hasDeepLink }: UseReaderTabsOpts) {
  // `doc` can already be in the query cache on the first render, so the landing
  // tab is decided here as well as in the effect. The visited flags have to
  // agree with it: a landing tab whose panel is not mounted renders one blank
  // frame before the effect latches the flag.
  const [initialTab] = useState<ReaderTab>(() => readerLandingTab(format, hasDeepLink))
  const [leftTab, setLeftTab] = useState<ReaderTab>(initialTab)
  // PDF View tab visited at least once -> mount and keep alive.
  const [pdfViewVisited, setPdfViewVisited] = useState(initialTab === "pdfview")
  // Book View tab visited at least once -> mount and keep alive.
  const [bookViewVisited, setBookViewVisited] = useState(initialTab === "bookview")

  useEffect(() => {
    if (leftTab === "pdfview") {
      if (format !== "pdf") {
        setLeftTab("read")
      } else {
        setPdfViewVisited(true)
      }
    } else if (leftTab === "bookview") {
      if (format !== "epub") {
        setLeftTab("read")
      } else {
        setBookViewVisited(true)
      }
    }
  }, [leftTab, format])

  return {
    leftTab,
    setLeftTab,
    pdfViewVisited,
    setPdfViewVisited,
    bookViewVisited,
    setBookViewVisited,
  }
}
