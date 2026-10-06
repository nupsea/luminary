/**
 * Chapter practice (#231): a document's chapters, admitting one to review, and the reader's
 * end-of-chapter offer.
 */

import { apiGet, apiPost, apiPut } from "@/lib/apiClient"
import type { Flashcard } from "@/lib/studyApi"
import type { components } from "@/types/api"

export type Chapter = components["schemas"]["ChapterItem"]
export type ChapterList = components["schemas"]["ChapterList"]

export const fetchChapters = (documentId: string) =>
  apiGet<ChapterList>(`/sections/${documentId}/chapters`)

/** Admits the chapter's held cards to review and returns all its cards. */
export const practiceChapter = (documentId: string, chapterId: string) =>
  apiPost<Flashcard[]>(`/sections/${documentId}/chapters/${chapterId}/practice`)

export const setAskAtChapterEnd = (documentId: string, ask: boolean) =>
  apiPut<void>(`/sections/${documentId}/chapters/prompt`, { ask_at_chapter_end: ask })

/** Where the reader is, as each view knows it: the Read view by section, the PDF view by page. */
export type ReaderPlace = { sectionId: string } | { page: number }

/** The chapter at *place*; undefined outside every chapter (front matter, a blank page between). */
export function chapterIndexAt(chapters: Chapter[], place: ReaderPlace): number | undefined {
  const i =
    "sectionId" in place
      ? chapters.findIndex((c) => c.section_ids.includes(place.sectionId))
      : chapters.findIndex(
          (c) => c.page_start > 0 && c.page_start <= place.page && place.page <= c.page_end,
        )
  return i < 0 ? undefined : i
}

/**
 * The chapter the reader just finished, when reading moved from one chapter into a later one.
 * Arriving in a chapter (a resumed position) counts the one before it as read, so a chapter
 * finished in an earlier visit is still offered. Moving back, or within a chapter, finishes nothing.
 */
export function finishedChapter(
  chapters: Chapter[],
  fromIndex: number | undefined,
  toIndex: number | undefined,
): Chapter | null {
  if (toIndex === undefined) return null
  if (fromIndex === undefined) return chapters[toIndex - 1] ?? null
  return toIndex > fromIndex ? (chapters[fromIndex] ?? null) : null
}

/** Offered only for a chapter that has cards nobody has practised yet. */
export function worthOffering(chapter: Chapter): boolean {
  return chapter.cards > 0 && chapter.held > 0
}

/**
 * What a finished chapter means for the reader now: offer it, wait for its questions to be
 * written, or neither (already practised, or the book asks not to be offered).
 */
export function chapterEndState(
  list: ChapterList | undefined,
  finishedId: string | null,
): { offer: Chapter | null; awaiting: boolean } {
  const chapter = list?.chapters.find((c) => c.id === finishedId)
  if (!list?.ask_at_chapter_end || !chapter) return { offer: null, awaiting: false }
  return { offer: worthOffering(chapter) ? chapter : null, awaiting: chapter.cards === 0 }
}

/**
 * A chapter to practise from the whole book, weighted toward chapters not practised yet:
 * an unpractised chapter is three times as likely as one already in review.
 */
export function pickChapter(chapters: Chapter[], random: () => number = Math.random): Chapter | null {
  const weights: number[] = chapters.map((c) => (c.cards === 0 ? 0 : c.held > 0 ? 3 : 1))
  const total = weights.reduce((a, b) => a + b, 0)
  if (total === 0) return null
  let target = random() * total
  for (let i = 0; i < chapters.length; i++) {
    target -= weights[i]
    if (target < 0) return chapters[i]
  }
  return chapters[chapters.length - 1]
}
