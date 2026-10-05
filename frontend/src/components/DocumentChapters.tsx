/**
 * DocumentChapters -- a book's chapters with their questions, on the Study page (#231).
 *
 * Shown once any chapter has cards. "Random" draws a chapter weighted toward the ones not
 * practised yet (`pickChapter`).
 */

import { useQuery } from "@tanstack/react-query"
import { BookOpen, Brain, MessageSquare, Shuffle } from "lucide-react"

import { type Chapter, fetchChapters, pickChapter } from "@/lib/chapterApi"
import type { StudyMode } from "@/lib/studySessionService"

export function DocumentChapters({
  documentId,
  onPractice,
}: {
  documentId: string
  onPractice: (chapter: Chapter, mode: StudyMode) => void
}) {
  const { data } = useQuery({
    queryKey: ["chapters", documentId],
    queryFn: () => fetchChapters(documentId),
    staleTime: 60_000,
  })
  const chapters = data?.chapters ?? []
  if (!chapters.some((c) => c.cards > 0)) return null

  function random() {
    const chapter = pickChapter(chapters)
    if (chapter) onPractice(chapter, "flashcard")
  }

  return (
    <div data-testid="document-chapters" className="mb-8 rounded-xl border border-border bg-card/40 p-5">
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
          <Shuffle size={14} /> Random from this book
        </button>
      </div>
      <div className="flex flex-col divide-y divide-border/50 rounded-md border border-border/60">
        {chapters.map((c) => (
          <div key={c.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
            <span className="min-w-0 flex-1 truncate text-foreground/90">{c.title}</span>
            <span className="shrink-0 text-xs text-muted-foreground">
              {c.cards === 0
                ? "not written yet"
                : c.held > 0
                  ? `${c.cards} new`
                  : `${c.due} due of ${c.cards}`}
            </span>
            {c.cards > 0 && (
              <span className="flex shrink-0 items-center gap-1">
                <button
                  onClick={() => onPractice(c, "flashcard")}
                  title="Recall this chapter's questions"
                  aria-label={`Recall ${c.title}`}
                  className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  <Brain size={14} />
                </button>
                <button
                  onClick={() => onPractice(c, "teachback")}
                  title="Explain this chapter's ideas"
                  aria-label={`Explain ${c.title}`}
                  className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  <MessageSquare size={13} />
                </button>
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
