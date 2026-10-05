/**
 * ChapterPracticePanel -- the Practice face while a chapter is being practised (#231).
 *
 * Starting admits the chapter's cards to review (POST .../practice), so the cards a run does
 * not reach still come due later; the run itself is the reader-sized slice of them.
 */

import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Brain, MessageSquareQuote, X } from "lucide-react"

import { type Chapter, practiceChapter } from "@/lib/chapterApi"
import {
  type PreparedStudySessionOutcome,
  type StudyMode,
  prepareSectionStudyFromCards,
} from "@/lib/studySessionService"

import { READER_CARD_LIMIT } from "./practiceDeck"
import { StartButton } from "./PracticePanel"
import { RecallRunner } from "./RecallRunner"

interface ChapterPracticePanelProps {
  documentId: string
  chapter: Chapter
  onJumpToSource: (sectionId: string) => void
  onClose: () => void
}

interface ChapterRun {
  mode: StudyMode
  initial: Exclude<PreparedStudySessionOutcome, { kind: "empty" }>
}

export function ChapterPracticePanel({
  documentId,
  chapter,
  onJumpToSource,
  onClose,
}: ChapterPracticePanelProps) {
  const qc = useQueryClient()
  const [run, setRun] = useState<ChapterRun | null>(null)
  const [starting, setStarting] = useState<StudyMode | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function start(mode: StudyMode) {
    setStarting(mode)
    setError(null)
    try {
      const cards = await practiceChapter(documentId, chapter.id)
      const initial = await prepareSectionStudyFromCards(
        documentId,
        cards.slice(0, READER_CARD_LIMIT),
        mode,
      )
      if (initial.kind === "empty") {
        setError("This chapter has no cards yet.")
        return
      }
      setRun({ mode, initial })
    } catch {
      setError("Could not start the chapter. Is the backend reachable?")
    } finally {
      setStarting(null)
      void qc.invalidateQueries({ queryKey: ["chapters", documentId] })
    }
  }

  function done() {
    setRun(null)
    void qc.invalidateQueries({ queryKey: ["chapters", documentId] })
    void qc.invalidateQueries({ queryKey: ["reader-deck", documentId] })
    onClose()
  }

  return (
    <div data-testid="chapter-practice" className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <div className="mx-auto flex w-full max-w-2xl items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">
              {run ? "Testing yourself on" : "Practice the chapter"}
            </p>
            <p className="line-clamp-2 text-sm font-medium text-foreground">{chapter.title}</p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close chapter practice"
            className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
          >
            <X size={16} />
          </button>
        </div>
      </div>
      {run ? (
        <RecallRunner
          key={run.initial.session.id}
          initial={run.initial}
          scopeForBeginNew={{ mode: run.mode, documentId, cardLimit: READER_CARD_LIMIT }}
          mode={run.mode}
          onJumpToSource={onJumpToSource}
          onDone={done}
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-auto p-4">
          <div className="mx-auto w-full max-w-2xl rounded-xl border border-border bg-card p-5">
            <p className="text-base font-medium text-foreground">
              {chapter.cards} question{chapter.cards === 1 ? "" : "s"} on this chapter.
            </p>
            <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
              Practising adds them to your review schedule, so the ones you miss come back.
            </p>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <StartButton
                testId="chapter-recall"
                icon={Brain}
                label="Recall"
                hint="Guess, then check"
                busy={starting === "flashcard"}
                disabled={starting !== null}
                onClick={() => void start("flashcard")}
              />
              <StartButton
                testId="chapter-explain"
                icon={MessageSquareQuote}
                label="Explain it"
                hint="Write, then get scored"
                busy={starting === "teachback"}
                disabled={starting !== null}
                onClick={() => void start("teachback")}
              />
            </div>
            {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
          </div>
        </div>
      )}
    </div>
  )
}
