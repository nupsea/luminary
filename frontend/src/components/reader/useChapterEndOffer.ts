/**
 * Which chapter the reader just finished, to offer practising it (#231).
 *
 * The views report where the reader is (`reach`); moving into a later chapter finishes the one
 * left. Asked once per chapter in a reading session ("Later" means not now, not never); the
 * "Don't ask for this book" choice is the document's and comes back with the chapters.
 */

import { useCallback, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"

import {
  type Chapter,
  type ReaderPlace,
  chapterIndexAt,
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

export function useChapterEndOffer(documentId: string) {
  const { data } = useQuery({
    queryKey: ["chapters", documentId],
    queryFn: () => fetchChapters(documentId),
    staleTime: 60_000,
  })
  const [offer, setOffer] = useState<Chapter | null>(null)
  const current = useRef<number | undefined>(undefined)

  const reach = useCallback(
    (place: ReaderPlace) => {
      const chapters = data?.chapters ?? []
      const here = chapterIndexAt(chapters, place)
      if (!data?.ask_at_chapter_end || here === undefined) return
      const ended = finishedChapter(chapters, current.current, here)
      current.current = here
      if (!ended || !worthOffering(ended)) return
      const asked = readAsked(documentId)
      if (asked.has(ended.id)) return
      asked.add(ended.id)
      rememberAsked(documentId, asked)
      setOffer(ended)
    },
    [data, documentId],
  )

  return { offer, reach, dismiss: () => setOffer(null) }
}
