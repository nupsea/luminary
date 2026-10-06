/**
 * Which chapter the reader just finished, to offer practising it (#231).
 *
 * The views report where the reader is (`reach`); moving into a later chapter finishes the one
 * left (`finishedChapter`). A chapter finished before its questions were written is offered
 * when they arrive. Asked once per chapter in a reading session ("Later" means not now, not
 * never); the "Don't ask for this book" choice is the document's and comes back with the chapters.
 */

import { useCallback, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"

import {
  type ReaderPlace,
  chapterEndState,
  chapterIndexAt,
  fetchChapters,
  finishedChapter,
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

// How often to look again for the questions of a chapter finished before they were written.
const AWAIT_CARDS_MS = 30_000

export function useChapterEndOffer(documentId: string) {
  // The chapter just finished; offered once its questions exist, which may be after it ends.
  const [finished, setFinished] = useState<string | null>(null)
  const { data } = useQuery({
    queryKey: ["chapters", documentId],
    queryFn: () => fetchChapters(documentId),
    staleTime: 60_000,
    refetchInterval: (query) =>
      chapterEndState(query.state.data, finished).awaiting ? AWAIT_CARDS_MS : false,
  })
  const current = useRef<number | undefined>(undefined)

  const reach = useCallback(
    (place: ReaderPlace) => {
      const chapters = data?.chapters ?? []
      const here = chapterIndexAt(chapters, place)
      if (here === undefined || here === current.current) return
      const ended = finishedChapter(chapters, current.current, here)
      current.current = here
      if (ended && !readAsked(documentId).has(ended.id)) setFinished(ended.id)
    },
    [data, documentId],
  )

  const { offer } = chapterEndState(data, finished)

  const dismiss = useCallback(() => {
    if (finished) {
      const asked = readAsked(documentId)
      asked.add(finished)
      rememberAsked(documentId, asked)
    }
    setFinished(null)
  }, [documentId, finished])

  return { offer, reach, dismiss }
}
