/**
 * DocumentChapters -- a book's chapters with their questions (#231), on the Study page and in
 * the reader's Practice dock.
 *
 * Shown once any chapter has cards. Picking a chapter, or "Random" (weighted toward chapters not
 * practised yet, `pickChapter`), either opens it (`onOpen`, the dock's own chapter panel) or
 * opens the count-and-mode choice under the row (`onPractice`, the Study page).
 */

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { BookOpen, ChevronRight, Shuffle } from "lucide-react"

import { ChapterPracticeSetup } from "@/components/ChapterPracticeSetup"
import { type Chapter, chapterStatus, fetchChapters, pickChapter } from "@/lib/chapterApi"
import type { StudyMode } from "@/lib/studySessionService"

type Action =
  | { onOpen: (chapter: Chapter) => void; onPractice?: never }
  | { onPractice: (chapter: Chapter, mode: StudyMode, count: number) => void; onOpen?: never }

export function DocumentChapters({
  documentId,
  className = "mb-8",
  ...action
}: { documentId: string; className?: string } & Action) {
  const [selected, setSelected] = useState<string | null>(null)
  const { data } = useQuery({
    queryKey: ["chapters", documentId],
    queryFn: () => fetchChapters(documentId),
    staleTime: 60_000,
  })
  const chapters = data?.chapters ?? []
  if (!chapters.some((c) => c.cards > 0)) return null

  function choose(chapter: Chapter) {
    if (action.onOpen) action.onOpen(chapter)
    else setSelected((id) => (id === chapter.id ? null : chapter.id))
  }

  function random() {
    const chapter = pickChapter(chapters)
    if (chapter) choose(chapter)
  }

  return (
    <div data-testid="document-chapters" className={`${className} rounded-xl border border-border bg-card/40 p-5`}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <BookOpen size={18} className="text-primary" />
          <h2 className="text-lg font-semibold text-foreground">Chapters</h2>
        </div>
        <button
          onClick={random}
          title="A chapter at random, favouring ones you have not practised"
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm text-foreground hover:bg-muted"
        >
          <Shuffle size={14} /> Random chapter
        </button>
      </div>
      <div className="flex flex-col divide-y divide-border/50 rounded-md border border-border/60">
        {chapters.map((c) => (
          <div key={c.id}>
            <button
              onClick={() => choose(c)}
              disabled={c.cards === 0}
              aria-expanded={action.onPractice ? selected === c.id : undefined}
              title={c.cards === 0 ? "Its questions are not written yet" : `Practise ${c.title}`}
              className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-muted/60 disabled:cursor-default disabled:hover:bg-transparent"
            >
              <span className="min-w-0 flex-1 truncate text-foreground/90">{c.title}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{chapterStatus(c)}</span>
              {c.cards > 0 && (
                <ChevronRight
                  size={14}
                  className={`shrink-0 text-muted-foreground transition-transform ${selected === c.id ? "rotate-90" : ""}`}
                />
              )}
            </button>
            {action.onPractice && selected === c.id && (
              <div className="border-t border-border/50 bg-background/60 px-3 py-4">
                <ChapterPracticeSetup
                  chapter={c}
                  starting={null}
                  onStart={(mode, count) => action.onPractice(c, mode, count)}
                />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
