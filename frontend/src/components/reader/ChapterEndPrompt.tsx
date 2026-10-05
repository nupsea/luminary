/**
 * The reader's offer to practise a chapter when reading moves past its end (#231).
 *
 * Asked once per chapter in a reading session ("Later" means not now, not never), and never
 * again for a book after "Don't ask for this book", which is stored on the document.
 */

import { useQueryClient } from "@tanstack/react-query"
import { GraduationCap, X } from "lucide-react"

import { type Chapter, setAskAtChapterEnd } from "@/lib/chapterApi"

export function ChapterEndPrompt({
  documentId,
  chapter,
  onPractice,
  onDismiss,
}: {
  documentId: string
  chapter: Chapter
  onPractice: (chapter: Chapter) => void
  onDismiss: () => void
}) {
  const qc = useQueryClient()

  async function never() {
    onDismiss()
    try {
      await setAskAtChapterEnd(documentId, false)
    } finally {
      void qc.invalidateQueries({ queryKey: ["chapters", documentId] })
    }
  }

  return (
    <div
      data-testid="chapter-end-prompt"
      role="dialog"
      aria-label="Practice this chapter"
      className="fixed bottom-6 left-1/2 z-40 w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border border-border bg-card p-4 shadow-lg"
    >
      <div className="flex items-start gap-3">
        <GraduationCap size={18} className="mt-0.5 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-foreground">
            You finished {chapter.title}.
          </p>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Practise its {chapter.cards} question{chapter.cards === 1 ? "" : "s"} while it is fresh?
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              onClick={() => {
                onDismiss()
                onPractice(chapter)
              }}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Practice
            </button>
            <button
              onClick={onDismiss}
              className="rounded-md border border-border px-3 py-1.5 text-sm text-foreground hover:bg-muted"
            >
              Later
            </button>
            <button
              onClick={() => void never()}
              className="px-2 py-1.5 text-sm text-muted-foreground underline-offset-2 hover:underline"
            >
              Don&apos;t ask for this book
            </button>
          </div>
        </div>
        <button
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 text-muted-foreground hover:text-foreground"
        >
          <X size={16} />
        </button>
      </div>
    </div>
  )
}
