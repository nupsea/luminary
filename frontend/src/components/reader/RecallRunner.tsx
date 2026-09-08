/**
 * RecallRunner -- one card at a time, beside the document it came from.
 *
 * The rule this surface exists to enforce: the answer is not rendered until
 * the learner has committed to something -- a confidence prediction, or an
 * explanation typed out. Hiding it behind a class would not do. A panel with
 * the answer in the DOM is a panel you can read ahead in, and reading ahead is
 * precisely what retrieval practice is not.
 *
 * Session lifecycle stays `useStudySession`'s: the session was created by the
 * click that started this run, never by a mount effect here (see the header of
 * useStudySession.ts for what that rule is protecting).
 */

import { useState } from "react"
import { Check, ChevronsUp, Loader2, Minus, RotateCcw, Send, Text, X } from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { InlineTeachbackFeedback } from "@/components/Teachback/InlineTeachbackFeedback"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { useTeachbackPolling } from "@/components/Teachback/useTeachbackPolling"
import { type UseStudySessionInput, useStudySession } from "@/hooks/useStudySession"
import {
  CALIBRATION_TEXT_CLASS,
  PREDICTIONS,
  RATING_CLASS,
  RATING_LABELS,
  RATING_ORDER,
  calibrationMessage,
  getSessionPhase,
  type CalibrationTone,
} from "@/lib/recallFeedback"
import {
  type Flashcard,
  type PendingTeachback,
  type Rating,
  type TeachbackResultItem,
  fetchSourceContext,
  submitReview,
  submitTeachbackAsync,
} from "@/lib/studyApi"
import type { StudyMode } from "@/lib/studySessionService"

const RATING_ICONS: Record<Rating, LucideIcon> = {
  again: RotateCcw,
  hard: Minus,
  good: Check,
  easy: ChevronsUp,
}

// The Study page's revealed-answer treatment, so a card reads the same in the
// dock as on the page. The heading clamps are the panel's own: prose sizes an
// h2 for a page, not for a column that can be 460px wide.
const ANSWER_PROSE =
  "text-base leading-relaxed text-foreground prose-p:my-2 prose-ul:my-2 prose-li:my-0.5 [&_h1]:text-base [&_h2]:text-base [&_h3]:text-sm [&_h1]:mt-0 [&_h2]:mt-3"

interface RecallRunnerProps {
  initial: UseStudySessionInput["initial"]
  scopeForBeginNew: UseStudySessionInput["scopeForBeginNew"]
  mode: StudyMode
  /** Put the document on the passage this card came from. */
  onJumpToSource: (sectionId: string) => void
  /** The run is over, or the learner left it. Back to the deck. */
  onDone: () => void
}

export function RecallRunner({
  initial,
  scopeForBeginNew,
  mode,
  onJumpToSource,
  onDone,
}: RecallRunnerProps) {
  const {
    sessionState,
    sessionId,
    queue,
    currentIndex,
    reviewed,
    total,
    currentCard,
    setCurrentIndex,
    setReviewed,
    completeSession,
    exit,
  } = useStudySession({ initial, scopeForBeginNew })

  // Per-card. `revealed` is the one that matters: everything the learner is
  // not supposed to see yet is behind it.
  const [predicted, setPredicted] = useState<Rating | null>(null)
  const [revealed, setRevealed] = useState(false)
  const [explanation, setExplanation] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [graded, setGraded] = useState<Rating | null>(null)
  // Where this card's answer lives in the document. Only some cards arrive
  // carrying it (see reveal).
  const [jumpSection, setJumpSection] = useState<string | null>(null)
  const [calibration, setCalibration] = useState<{ text: string; tone: CalibrationTone } | null>(null)

  // Run totals.
  const [correct, setCorrect] = useState(0)
  const [predictionsMade, setPredictionsMade] = useState(0)
  const [predictionsCalibrated, setPredictionsCalibrated] = useState(0)
  const [pending, setPending] = useState<PendingTeachback[]>([])

  const { results, stats } = useTeachbackPolling(pending)
  const cardResult = currentCard
    ? results?.find((r) => r.flashcard_id === currentCard.id)
    : undefined

  function reveal(card: Flashcard) {
    setRevealed(true)
    if (card.section_id) {
      setJumpSection(card.section_id)
      onJumpToSource(card.section_id)
      return
    }
    // Only `GET /study/due` joins the section onto a card. A resumed session's
    // remaining cards and a deck run that was not due both arrive without it
    // (study.py:1333), so ask for the locus rather than dropping the jump --
    // landing on the passage is the reason to practise inside the reader.
    void (async () => {
      const ctx = await fetchSourceContext(card.id)
      if (ctx?.section_id) {
        setJumpSection(ctx.section_id)
        onJumpToSource(ctx.section_id)
      }
    })()
  }

  function handlePredict(rating: Rating) {
    setPredicted(rating)
    if (currentCard) reveal(currentCard)
  }

  async function handleSubmitExplanation() {
    if (!currentCard || submitting || explanation.trim().length === 0) return
    setSubmitting(true)
    try {
      const { id } = await submitTeachbackAsync(currentCard.id, explanation.trim(), sessionId)
      setPending((p) => [...p, { id, flashcardId: currentCard.id, question: currentCard.question }])
    } catch {
      // The explanation is still worth revealing against: scoring is the extra,
      // not the point. An unscored card is marked as such below.
      setPending((p) => [
        ...p,
        { id: `error-${currentCard.id}`, flashcardId: currentCard.id, question: currentCard.question },
      ])
    } finally {
      setSubmitting(false)
      reveal(currentCard)
    }
  }

  function advance() {
    setPredicted(null)
    setRevealed(false)
    setExplanation("")
    setGraded(null)
    setCalibration(null)
    setJumpSection(null)
    const nextIdx = currentIndex + 1
    if (nextIdx >= queue.length) {
      void completeSession()
    } else {
      setCurrentIndex(nextIdx)
    }
  }

  async function handleGrade(rating: Rating) {
    if (!currentCard || !sessionId || graded) return
    await submitReview(currentCard.id, rating, sessionId, predicted ?? undefined)
    setReviewed((r) => r + 1)
    if (rating !== "again") setCorrect((c) => c + 1)

    if (predicted !== null) {
      const cal = calibrationMessage(predicted, rating)
      setPredictionsMade((n) => n + 1)
      if (cal.calibrated) setPredictionsCalibrated((n) => n + 1)
      setCalibration({ text: cal.text, tone: cal.tone })
      // The cards you got wrong are where the reflection is worth a beat, so
      // those hold; the ones you knew keep the loop moving.
      if (rating === "again" || rating === "hard") {
        setGraded(rating)
        return
      }
    } else if (rating === "again" || rating === "hard") {
      setGraded(rating)
      return
    }
    advance()
  }

  if (sessionState === "complete") {
    return (
      <Readout
        mode={mode}
        reviewed={reviewed}
        correct={correct}
        predictionsMade={predictionsMade}
        predictionsCalibrated={predictionsCalibrated}
        teachbackAvg={stats.avgScore}
        teachbackDone={stats.completedCount}
        onDone={onDone}
      />
    )
  }

  if (!currentCard) {
    return (
      <div className="p-4 text-xs text-muted-foreground">
        This run has no cards left.{" "}
        <button onClick={onDone} className="underline hover:no-underline">
          Back to the deck
        </button>
      </div>
    )
  }

  const phase = getSessionPhase(currentIndex, total)
  const pct = total === 0 ? 0 : Math.round((reviewed / total) * 100)

  return (
    <div data-testid="recall-runner" className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-border px-4 py-2.5">
        <div className="mx-auto flex w-full max-w-2xl items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${phase.style}`}>
              {phase.label}
            </span>
            <span className="text-xs text-muted-foreground">
              {reviewed} of {total} reviewed
            </span>
          </div>
          <button
            onClick={() => void exit(onDone)}
            aria-label="Leave this run"
            title="Leave this run"
            className="text-muted-foreground transition-colors hover:text-foreground"
          >
            <X size={16} />
          </button>
        </div>
        <div className="mx-auto mt-2 h-1.5 w-full max-w-2xl overflow-hidden rounded-full bg-secondary">
          <div
            className="h-full rounded-full bg-primary transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* The column, not a viewport breakpoint, is what handles width here: the
          panel is dragged between 280 and 900px independently of the window. */}
      <div className="min-h-0 flex-1 overflow-auto p-4">
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-5">
          {/* The card, sized the way the Study page sizes it: the question
              carries the weight until the answer arrives, then yields to it. */}
          <div className="rounded-xl border border-border bg-card p-5 shadow-sm">
            {revealed ? (
              <div className="flex flex-col gap-4">
                <p
                  data-testid="recall-question"
                  className="text-sm leading-relaxed text-muted-foreground"
                >
                  {currentCard.question}
                </p>
                <hr className="border-border" />
                <div data-testid="recall-answer">
                  <MarkdownRenderer className={ANSWER_PROSE}>
                    {currentCard.answer}
                  </MarkdownRenderer>
                </div>
              </div>
            ) : (
              <p
                data-testid="recall-question"
                className="text-lg font-semibold leading-snug text-foreground"
              >
                {currentCard.question}
              </p>
            )}
          </div>

          {!revealed && mode === "flashcard" && (
            <div className="flex flex-col gap-3">
              <div>
                <p className="text-xs uppercase tracking-wider text-muted-foreground/70">
                  Before you look
                </p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Answer it in your head first, then say how that went.
                </p>
              </div>
              <div className="grid grid-cols-3 gap-2">
                {PREDICTIONS.map((p) => (
                  <button
                    key={p.value}
                    data-testid={`predict-${p.value}`}
                    onClick={() => handlePredict(p.value)}
                    className={`rounded-lg border px-3 py-3 text-sm font-medium transition-colors ${RATING_CLASS[p.value]}`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {!revealed && mode === "teachback" && (
            <div className="flex flex-col gap-3">
              <p className="text-xs uppercase tracking-wider text-muted-foreground/70">
                Explain it in your own words
              </p>
              <textarea
                value={explanation}
                onChange={(e) => setExplanation(e.target.value)}
                rows={7}
                placeholder="Say it the way you would to someone who has not read this."
                className="w-full resize-y rounded-lg border border-border bg-background p-3 text-sm leading-relaxed text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              />
              <button
                onClick={() => void handleSubmitExplanation()}
                disabled={submitting || explanation.trim().length === 0}
                className="flex items-center gap-2 self-start rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {submitting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                Submit and compare
              </button>
            </div>
          )}

          {revealed && (
            <>
              {mode === "teachback" && (
                <TeachbackVerdict
                  result={cardResult}
                  // Per card, not per run: a single failed submission used to mark
                  // every card after it unscored, including the ones that scored.
                  failed={pending.some(
                    (p) => p.flashcardId === currentCard.id && p.id.startsWith("error-"),
                  )}
                />
              )}

              {currentCard.source_excerpt && (
                <div className="rounded-lg border border-border bg-muted/30 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-xs uppercase tracking-wider text-muted-foreground/70">
                      From the document
                    </p>
                    {jumpSection && (
                      <button
                        data-testid="recall-jump"
                        onClick={() => onJumpToSource(jumpSection)}
                        className="flex shrink-0 items-center gap-1.5 text-xs font-medium text-primary hover:underline"
                      >
                        <Text size={12} />
                        Show me
                      </button>
                    )}
                  </div>
                  <p className="mt-2 text-sm italic leading-relaxed text-muted-foreground">
                    {currentCard.source_excerpt}
                  </p>
                </div>
              )}

              {calibration && (
                <p className={`text-sm font-medium ${CALIBRATION_TEXT_CLASS[calibration.tone]}`}>
                  {calibration.text}
                </p>
              )}

              {graded ? (
                <button
                  onClick={advance}
                  className="self-start rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                >
                  Next card
                </button>
              ) : (
                <div>
                  <p className="text-xs uppercase tracking-wider text-muted-foreground/70">
                    How did that go?
                  </p>
                  <div className="mt-2 grid grid-cols-4 gap-2">
                    {RATING_ORDER.map((r) => {
                      const Icon = RATING_ICONS[r]
                      return (
                        <button
                          key={r}
                          data-testid={`grade-${r}`}
                          onClick={() => void handleGrade(r)}
                          className={`flex flex-col items-center gap-1 rounded-lg border px-2 py-2.5 text-sm font-medium transition-colors ${RATING_CLASS[r]}`}
                        >
                          <Icon size={15} />
                          {RATING_LABELS[r]}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function TeachbackVerdict({
  result,
  failed,
}: {
  result: TeachbackResultItem | undefined
  failed: boolean
}) {
  if (result && result.status === "complete") {
    return <InlineTeachbackFeedback result={result} />
  }
  if (result?.status === "error" || failed) {
    return (
      <p className="rounded border border-destructive/40 bg-destructive/10 px-2 py-1.5 text-xs text-destructive">
        Your explanation could not be scored. Compare it against the answer yourself.
      </p>
    )
  }
  return (
    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <Loader2 size={12} className="animate-spin" />
      Scoring your explanation...
    </p>
  )
}
function Readout({
  mode,
  reviewed,
  correct,
  predictionsMade,
  predictionsCalibrated,
  teachbackAvg,
  teachbackDone,
  onDone,
}: {
  mode: StudyMode
  reviewed: number
  correct: number
  predictionsMade: number
  predictionsCalibrated: number
  teachbackAvg: number
  teachbackDone: number
  onDone: () => void
}) {
  return (
    <div
      data-testid="recall-readout"
      className="min-h-0 flex-1 overflow-auto p-4"
    >
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-5">
        <p className="text-lg font-semibold text-foreground">Run finished</p>

        <div className="grid grid-cols-2 gap-3">
          <Stat label="Reviewed" value={String(reviewed)} />
          <Stat label="Got right" value={reviewed === 0 ? "--" : `${correct} of ${reviewed}`} />
        </div>

        {mode === "flashcard" && predictionsMade > 0 && (
          <div className="rounded-xl border border-border bg-card p-5">
            <p className="text-xs uppercase tracking-wider text-muted-foreground/70">
              What you thought you knew
            </p>
            <p className="mt-2 text-base leading-relaxed text-foreground">
              {predictionsCalibrated} of {predictionsMade} predictions matched how the card
              actually went.
            </p>
            <p className="mt-1.5 text-sm text-muted-foreground">
              The gap between those two is the part worth studying.
            </p>
          </div>
        )}

        {mode === "teachback" && teachbackDone > 0 && (
          <div className="rounded-xl border border-border bg-card p-5">
            <p className="text-xs uppercase tracking-wider text-muted-foreground/70">
              Your explanations
            </p>
            <p className="mt-2 text-base leading-relaxed text-foreground">
              {teachbackDone} scored, averaging {teachbackAvg}/100.
            </p>
          </div>
        )}
        {mode === "teachback" && teachbackDone === 0 && (
          <p className="text-sm text-muted-foreground">
            No explanation has finished scoring yet. They keep scoring in the background.
          </p>
        )}

        <button
          onClick={onDone}
          className="self-start rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          Back to the deck
        </button>
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs uppercase tracking-wider text-muted-foreground/70">{label}</p>
      <p className="mt-1.5 text-xl font-semibold text-foreground">{value}</p>
    </div>
  )
}
