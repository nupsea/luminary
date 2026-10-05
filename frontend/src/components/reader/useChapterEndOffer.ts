/**
 * Which chapter the reader just finished, to offer practising it (#231).
 *
 * Asked once per chapter in a reading session ("Later" means not now, not never); the
 * "Don't ask for this book" choice is the document's and comes back with the chapters.
 */

import { useEffect, useMemo, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"

import {
  type Chapter,
  chapterIndexBySection,
  fetchChapters,
  finishedChapter,
  worthOffering,
} from "@/lib/chapterApi"

function askedKey(documentId: string) {
  return `chapter-asked-${documentId}`
}

function readAsked(documentId: string): Set<string> {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(askedKey(documentId)) ?? "[]") as string[])
  } catch {
    return new Set()
  }
}

function rememberAsked(documentId: string, asked: Set<string>) {
  try {
    sessionStorage.setItem(askedKey(documentId), JSON.stringify([...asked]))
  } catch {
    // Without storage the offer can repeat this session; it still never repeats after "Don't ask".
  }
}

/** The chapter to offer, from the topmost section the reader can see. */
export function useChapterEndOffer(documentId: string, sectionCount: number) {
  const { data } = useQuery({
    queryKey: ["chapters", documentId],
    queryFn: () => fetchChapters(documentId),
    staleTime: 60_000,
  })
  const chapters = useMemo(() => data?.chapters ?? [], [data])
  const index = useMemo(() => chapterIndexBySection(chapters), [chapters])
  const [offer, setOffer] = useState<Chapter | null>(null)
  const current = useRef<number | undefined>(undefined)

  useEffect(() => {
    if (!data?.ask_at_chapter_end || chapters.length < 2 || sectionCount === 0) return
    const elements = Array.from(document.querySelectorAll<HTMLElement>("[data-section-id]"))
    // Every visible section, not just the entries this callback reports: the topmost one is
    // where the reader is.
    const visible = new Map<string, number>()
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const sid = (e.target as HTMLElement).dataset.sectionId ?? ""
          if (e.isIntersecting) visible.set(sid, e.boundingClientRect.top)
          else visible.delete(sid)
        }
        if (visible.size === 0) return
        const [topId] = [...visible.entries()].reduce((a, b) => (a[1] <= b[1] ? a : b))
        const next = index.get(topId)
        const ended = finishedChapter(chapters, current.current, next)
        if (next !== undefined) current.current = next
        if (!ended || !worthOffering(ended)) return
        const asked = readAsked(documentId)
        if (asked.has(ended.id)) return
        asked.add(ended.id)
        rememberAsked(documentId, asked)
        setOffer(ended)
      },
      { threshold: 0.2 },
    )
    for (const el of elements) observer.observe(el)
    return () => observer.disconnect()
  }, [data, chapters, index, documentId, sectionCount])

  return { offer, dismiss: () => setOffer(null) }
}

