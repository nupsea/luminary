import { useEffect, useState } from "react"

export type ReaderTab = "sections" | "pdfview" | "bookview" | "read"

interface UseReaderTabsOpts {
  format: string | undefined
}

// Owns the left-panel tab state and the lazy-mount visited flags. Format
// mismatches (e.g. user is on the pdfview tab but the document isn't a PDF)
// are corrected automatically.
export function useReaderTabs({ format }: UseReaderTabsOpts) {
  const [leftTab, setLeftTab] = useState<ReaderTab>("sections")
  // PDF View tab visited at least once -> mount and keep alive.
  const [pdfViewVisited, setPdfViewVisited] = useState(false)
  // Book View tab visited at least once -> mount and keep alive.
  const [bookViewVisited, setBookViewVisited] = useState(false)

  useEffect(() => {
    if (leftTab === "pdfview") {
      if (format !== "pdf") {
        setLeftTab("sections")
      } else {
        setPdfViewVisited(true)
      }
    } else if (leftTab === "bookview") {
      if (format !== "epub") {
        setLeftTab("sections")
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
