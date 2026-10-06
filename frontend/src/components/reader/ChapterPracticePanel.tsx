/**
 * ChapterPracticePanel -- the Practice face while a chapter is being practised (#231).
 *
 * The run is the cards drawn by POST .../practice; only those join review, the rest stay new.
 */

import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { X } from "lucide-react"

import { ChapterPracticeSetup } from "@/components/ChapterPracticeSetup"
import { type Chapter, practiceChapter } from "@/lib/chapterApi"
import {
  type PreparedStudySessionOutcome,
  type StudyMode,
  prepareSectionStudyFromCards,
} from "@/lib/studySessionService"

import { READER_CARD_LIMIT } from "./practiceDeck"
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

  async function start(mode: StudyMode, count: number) {
    setStarting(mode)
    setError(null)
    try {
      const cards = await practiceChapter(documentId, chapter.id, count)
      const initial = await prepareSectionStudyFromCards(documentId, cards, mode)
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
            <ChapterPracticeSetup
              chapter={chapter}
              starting={starting}
              onStart={(mode, count) => void start(mode, count)}
            />
            {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
          </div>
        </div>
      )}
    </div>
  )
}
