import { useCallback, useEffect, useRef, useState } from "react"

import { ApiError, apiDelete, apiGet, apiPut, request } from "@/lib/apiClient"
import { epubPlaceOf, type EpubPlace } from "../epubPlace"
import type { ReadingPosition } from "../ResumeBanner"
import { NOWHERE, placeOfPosition, positionBody, settledSaver, withSaved, type ReadPlace } from "./positionSave"

// A page or EPUB place counts as read once the reader has stopped on it this long.
const PLACE_SETTLE_MS = 2_000

const dismissedKey = (documentId: string) => `resume-dismissed-${documentId}`

/**
 * A document's saved reading place and bookmark, and the saving of where the reader goes
 * in the Read view (by section), the PDF view (by page) and the Book View (by EPUB place).
 *
 * Nothing is saved until the saved place is known: a save sends every view's place, and
 * one sent before then would blank the views not yet read.
 */
export function useReadingPlace(documentId: string, sections: readonly { id: string; heading: string }[] | undefined) {
  const [loaded, setLoaded] = useState(false)
  const [resume, setResume] = useState<ReadingPosition | null>(null)
  const [pdfOpenOn, setPdfOpenOn] = useState<number | null>(null)
  const [epubOpenOn, setEpubOpenOn] = useState<EpubPlace | null>(null)
  const [pdfBookmark, setPdfBookmarkState] = useState<number | null>(null)
  const [epubBookmark, setEpubBookmarkState] = useState<EpubPlace | null>(null)

  const placeRef = useRef<ReadPlace>(NOWHERE)
  // The body last saved, or null while the saved place is unknown.
  const savedRef = useRef<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const sectionsRef = useRef(sections)
  useEffect(() => { sectionsRef.current = sections }, [sections])

  const save = useCallback((keepalive: boolean) => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = null
    const body = positionBody(placeRef.current)
    const key = JSON.stringify(body)
    if (savedRef.current == null || key === savedRef.current) return
    savedRef.current = key
    void request(`/documents/${documentId}/position`, { method: "POST", keepalive, body }).catch(() => {})
  }, [documentId])

  const saveSoon = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => save(false), PLACE_SETTLE_MS)
  }, [save])

  useEffect(() => {
    const dismissed = Boolean(sessionStorage.getItem(dismissedKey(documentId)))
    void apiGet<ReadingPosition>(`/documents/${documentId}/position`)
      .then((pos) => {
        const saved = placeOfPosition(pos)
        placeRef.current = withSaved(placeRef.current, saved)
        savedRef.current = JSON.stringify(positionBody(saved))
        const epubBookmarkPlace = epubPlaceOf(pos.epub_bookmark_chapter_index, pos.epub_bookmark_block_index)
        setPdfBookmarkState(pos.pdf_bookmark_page)
        setEpubBookmarkState(epubBookmarkPlace)
        setPdfOpenOn(pos.pdf_bookmark_page ?? (dismissed ? null : saved.pdfPage))
        setEpubOpenOn(epubBookmarkPlace ?? (dismissed ? null : saved.epubPlace))
        if (!dismissed && (saved.sectionId || saved.pdfPage != null || saved.epubPlace)) setResume(pos)
      })
      .catch((err) => {
        // 404 is a book never opened. Any other failure leaves saving off rather than
        // overwrite a saved place this session could not read.
        if (err instanceof ApiError && err.status === 404) savedRef.current = JSON.stringify(positionBody(NOWHERE))
      })
      .finally(() => {
        setLoaded(true)
        save(false)
      })
  }, [documentId, save])

  const sectionSaverRef = useRef<ReturnType<typeof settledSaver<string>> | null>(null)
  useEffect(() => {
    const sectionSaver = settledSaver<string>((sectionId) => {
      const heading = sectionsRef.current?.find((s) => s.id === sectionId)?.heading ?? null
      placeRef.current = { ...placeRef.current, sectionId, heading }
      save(false)
    })
    sectionSaverRef.current = sectionSaver
    // A save still pending when the reader closes or the tab hides would be lost.
    const onVisibility = () => { if (document.visibilityState === "hidden") save(true) }
    document.addEventListener("visibilitychange", onVisibility)
    return () => {
      sectionSaver.stop()
      document.removeEventListener("visibilitychange", onVisibility)
      save(true)
    }
  }, [save])

  const readSection = useCallback((sectionId: string) => sectionSaverRef.current?.reach(sectionId), [])

  const readPdfPage = useCallback((page: number) => {
    placeRef.current = { ...placeRef.current, pdfPage: page }
    saveSoon()
  }, [saveSoon])

  const readEpubPlace = useCallback((place: EpubPlace, chapterTitle: string) => {
    placeRef.current = { ...placeRef.current, epubPlace: place, heading: chapterTitle }
    saveSoon()
  }, [saveSoon])

  const putBookmark = useCallback(
    (body: object | null) =>
      body == null
        ? apiDelete(`/documents/${documentId}/bookmark`)
        : apiPut(`/documents/${documentId}/bookmark`, body),
    [documentId],
  )

  const setPdfBookmark = useCallback((page: number | null) => {
    const previous = pdfBookmark
    setPdfBookmarkState(page)
    putBookmark(page == null ? null : { pdf_page: page }).catch(() => setPdfBookmarkState(previous))
  }, [pdfBookmark, putBookmark])

  const setEpubBookmark = useCallback((place: EpubPlace | null) => {
    const previous = epubBookmark
    setEpubBookmarkState(place)
    putBookmark(place == null ? null : { epub_chapter_index: place.chapter, epub_block_index: place.block })
      .catch(() => setEpubBookmarkState(previous))
  }, [epubBookmark, putBookmark])

  const endResume = useCallback(() => {
    setResume(null)
    sessionStorage.setItem(dismissedKey(documentId), "1")
  }, [documentId])

  return {
    loaded,
    resume,
    endResume,
    readSection,
    pdf: { openOn: pdfOpenOn, bookmark: pdfBookmark, setBookmark: setPdfBookmark, read: readPdfPage },
    epub: { openOn: epubOpenOn, bookmark: epubBookmark, setBookmark: setEpubBookmark, read: readEpubPlace },
  }
}
