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

export function chapterIndexBySection(chapters: Chapter[]): Map<string, number> {
  const index = new Map<string, number>()
  chapters.forEach((c, i) => c.section_ids.forEach((sid) => index.set(sid, i)))
  return index
}

/**
 * The chapter the reader just finished, when reading moved from one chapter into a later one.
 * Moving back, or jumping inside a chapter, finishes nothing.
 */
export function finishedChapter(
  chapters: Chapter[],
  fromIndex: number | undefined,
  toIndex: number | undefined,
): Chapter | null {
  if (fromIndex === undefined || toIndex === undefined || toIndex <= fromIndex) return null
  return chapters[fromIndex] ?? null
}

/** Offered only for a chapter that has cards nobody has practised yet. */
export function worthOffering(chapter: Chapter): boolean {
  return chapter.cards > 0 && chapter.held > 0
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
