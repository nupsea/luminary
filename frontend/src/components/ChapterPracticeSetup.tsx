/**
 * How many of a chapter's questions to practise, and how (#231). The reader's dock and the
 * Study page both start a chapter run from here.
 */

import { useState } from "react"
import { Brain, MessageSquareQuote } from "lucide-react"

import { type Chapter, defaultDrawCount } from "@/lib/chapterApi"
import type { StudyMode } from "@/lib/studySessionService"

import { StartButton } from "./reader/StartButton"

export function ChapterPracticeSetup({
  chapter,
  starting,
  onStart,
}: {
  chapter: Chapter
  starting: StudyMode | null
  onStart: (mode: StudyMode, count: number) => void
}) {
  const [count, setCount] = useState(() => defaultDrawCount(chapter))

  return (
    <div data-testid="chapter-practice-setup">
      <label className="flex items-center justify-between gap-3 text-sm text-foreground">
        <span>How many questions?</span>
        <span data-testid="chapter-draw-count" className="font-medium tabular-nums">
          {count} of {chapter.cards}
        </span>
      </label>
      <input
        type="range"
        min={1}
        max={chapter.cards}
        value={count}
        onChange={(e) => setCount(Number(e.target.value))}
        aria-label="Number of questions"
        className="mt-2 w-full accent-primary"
      />
      <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
        Drawn at random from the chapter
        {chapter.held > 0 && chapter.held < chapter.cards
          ? `, the ${chapter.held} you have not practised first`
          : ""}
        . The ones you practise join your reviews; the rest wait here for next time.
      </p>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <StartButton
          testId="chapter-recall"
          icon={Brain}
          label="Recall"
          hint="Guess, then check"
          busy={starting === "flashcard"}
          disabled={starting !== null}
          onClick={() => onStart("flashcard", count)}
        />
        <StartButton
          testId="chapter-explain"
          icon={MessageSquareQuote}
          label="Explain it"
          hint="Write, then get scored"
          busy={starting === "teachback"}
          disabled={starting !== null}
          onClick={() => onStart("teachback", count)}
        />
      </div>
    </div>
  )
}
