import { useCallback, useEffect, useRef, useState } from "react"

import type { ReaderTab } from "./useReaderTabs"

export interface ReaderPlace {
  tab: ReaderTab
  sectionId: string | null
  pdfPage: number | null
}

interface UseReaderHistoryOpts {
  currentPlace: ReaderPlace
  navigateTo: (place: ReaderPlace) => void
}

// In-document navigation stack: every user-initiated navigation (tab change,
// Read click, PDF jump, citation deep-link) pushes the current place. goBack
// pops one and hands it to navigateTo, which the consumer wires up to the
// state setters (leftTab, sectionId, pdfPage).
export function useReaderHistory({ currentPlace, navigateTo }: UseReaderHistoryOpts) {
  const historyRef = useRef<ReaderPlace[]>([])
  const currentPlaceRef = useRef<ReaderPlace>(currentPlace)
  const [historyDepth, setHistoryDepth] = useState(0)

  useEffect(() => {
    currentPlaceRef.current = currentPlace
  }, [currentPlace])

  // override lets the caller pin the "place to return to" — e.g. a Read button
  // click should return to the clicked section, not to whichever activeSectionId
  // happened to be set when the click fired.
  const pushHistory = useCallback((override?: Partial<ReaderPlace>) => {
    const base = { ...currentPlaceRef.current }
    historyRef.current.push({ ...base, ...override })
    setHistoryDepth(historyRef.current.length)
  }, [])

  const goBack = useCallback(() => {
    const prev = historyRef.current.pop()
    setHistoryDepth(historyRef.current.length)
    if (prev) navigateTo(prev)
  }, [navigateTo])

  return { historyDepth, pushHistory, goBack }
}
