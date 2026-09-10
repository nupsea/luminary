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
import {
  ArrowRight,
  Check,
  ChevronsUp,
  Loader2,
  Minus,
  Plus,
  RotateCcw,
  Send,
  Text,
  X,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { ExpandableResultRow } from "@/components/Teachback/ExpandableResultRow"
import { InlineTeachbackFeedback } from "@/components/Teachback/InlineTeachbackFeedback"
import { VoiceRecordButton } from "@/components/VoiceRecordButton"
import { standingAttempts } from "@/components/Teachback/latestAttempts"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { useTeachbackPolling } from "@/components/Teachback/useTeachbackPolling"
import { answerCheckNote, sourceNote } from "@/lib/cardSourceNote"
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
  appendSessionCards,
  fetchSourceContext,
  reopenSession,
  submitReview,
  submitTeachbackAsync,
} from "@/lib/studyApi"
import type { StudyMode } from "@/lib/studySessionService"
import { advanceLabel } from "./practiceDeck"

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
  /**
   * Write more cards for this run's scope and hand them back. Offered on the
   * summary, where "keep going" is the thing a learner actually wants and the
   * old panel made them leave the run to get.
   */
  onGenerateMore?: (count: number) => Promise<Flashcard[]>
  /**
   * Set when the scope has no material left to write from, which is why
   * `onGenerateMore` is absent. Said rather than left blank: a control that
   * disappears with no explanation reads as a bug.
   */
  exhaustedNote?: string | null
  /**
   * What to say when a generation call returns nothing. Composed by the panel,
   * which is what holds the headroom: an empty result is not evidence that the
   * material ran out, and this used to claim it was.
   */
  noCardsNote?: string | null
}

export function RecallRunner({
  initial,
  scopeForBeginNew,
  mode,
  onJumpToSource,
  onDone,
  onGenerateMore,
  exhaustedNote,
  noCardsNote,
}: RecallRunnerProps) {
  const {
    sessionState,
    sessionId,
    queue,
    currentIndex,
    reviewed,
    total,
    currentCard,
    setQueue,
    setCurrentIndex,
    setReviewed,
    setTotal,
    setSessionState,
    completeSession,
    exit,
  } = useStudySession({
    initial,
    scopeForBeginNew,
    // A resumed run arrives with the explanations it already collected, so the
    // summary at the end is the whole run and not just what came after the
    // interruption.
    onResumeLoaded: (prev) => {
      setPending(
        prev.map((r) => ({ id: r.id, flashcardId: r.flashcard_id, question: r.question })),
      )
      // The resumed count already includes these cards. Without seeding the set,
      // re-answering one the learner answered in an earlier sitting counted it a
      // second time, and a continuous run drifted past its own total the longer
      // it was kept open.
      setCountedCards(new Set(prev.map((r) => r.flashcard_id)))
    },
  })

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
  // The card pulled back out of the finished summary, if any. Advancing from it
  // returns to the summary rather than walking on through the queue.
  const [retryTarget, setRetryTarget] = useState<string | null>(null)
  // Which cards have been counted as reviewed. A card answered twice -- in-run
  // with "Answer again", or from the summary -- is one card reviewed, and the
  // run's own header said "4 of 3 reviewed" until this was a set of ids.
  const [countedCards, setCountedCards] = useState<Set<string>>(new Set())
  const [calibration, setCalibration] = useState<{ text: string; tone: CalibrationTone } | null>(null)

  // Run totals.
  const [correct, setCorrect] = useState(0)
  // WHICH count is in flight, not merely whether one is: a single boolean
  // spun the loader on all three buttons at once, so the run appeared to be
  // writing 3, 5 and 10 cards simultaneously.
  const [addingCount, setAddingCount] = useState<number | null>(null)
  const [addError, setAddError] = useState<string | null>(null)
  const [predictionsMade, setPredictionsMade] = useState(0)
  const [predictionsCalibrated, setPredictionsCalibrated] = useState(0)
  const [pending, setPending] = useState<PendingTeachback[]>([])

  const { results, stats } = useTeachbackPolling(pending)
  // The LATEST attempt on this card, not the first. A card can be answered more
  // than once, and matching on flashcard_id alone showed the verdict of the
  // attempt the learner had already decided to improve on.
  const attemptsForCard = currentCard
    ? pending.filter((p) => p.flashcardId === currentCard.id)
    : []
  const latestAttemptId = attemptsForCard[attemptsForCard.length - 1]?.id ?? null
  const cardResult = results?.find((r) => r.id === latestAttemptId)
  const completedForCard = currentCard
    ? (results ?? []).filter(
        (r) => r.flashcard_id === currentCard.id && r.status === "complete",
      )
    : []
  const previousAttempt = completedForCard[completedForCard.length - 1] ?? null

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

  // A button names where it goes: the last card of the queue and a card pulled
  // back out of the summary both land on the readout, and both said "Next card".
  const nextLabel = advanceLabel({
    fromSummary: retryTarget !== null,
    index: currentIndex,
    queueLength: queue.length,
  })

  function advance(countReviewed = false) {
    if (countReviewed) countCard(currentCard?.id)
    setPredicted(null)
    setRevealed(false)
    setExplanation("")
    setGraded(null)
    setCalibration(null)
    setJumpSection(null)
    // A card reached back out of the summary goes back to the summary. It is
    // not a position in the queue, so the queue does not move.
    if (retryTarget !== null) {
      setRetryTarget(null)
      void completeSession()
      return
    }
    const nextIdx = currentIndex + 1
    if (nextIdx >= queue.length) {
      void completeSession()
    } else {
      setCurrentIndex(nextIdx)
    }
  }

  /** Count a card once, however many explanations or grades it took.
   *
   * The bump lives outside the set updater on purpose: StrictMode invokes an
   * updater twice, so a counter incremented inside one counts twice. */
  function countCard(cardId: string | undefined) {
    if (!cardId || countedCards.has(cardId)) return
    setCountedCards((seen) => new Set(seen).add(cardId))
    setReviewed((r) => r + 1)
  }

  /** Same card, blank box, with the last verdict kept in view to improve on. */
  function answerAgain() {
    setRevealed(false)
    setExplanation("")
    setJumpSection(null)
  }

  /** A card reached back out of the finished summary. */
  async function reAnswer(cardId: string) {
    const index = queue.findIndex((c) => c.id === cardId)
    if (index < 0 || !sessionId) return
    // The run is over, so its session was ended. Reopening keeps the retry in
    // the same run rather than opening a second one for one card.
    await reopenSession(sessionId).catch(() => {})
    // Move to the card, never replace the queue with it. Cutting the queue down
    // to the one card being retried meant the summary's other "Answer this one
    // again" buttons could no longer find their card, and silently did nothing.
    setRetryTarget(cardId)
    setCurrentIndex(index)
    setRevealed(false)
    setExplanation("")
    setJumpSection(null)
    setPredicted(null)
    setGraded(null)
    setCalibration(null)
    setSessionState("studying")
  }

  async function handleGrade(rating: Rating) {
    if (!currentCard || !sessionId || graded) return
    await submitReview(currentCard.id, rating, sessionId, predicted ?? undefined)
    countCard(currentCard.id)
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

  /**
   * More questions on the same run, rather than a second run beside it.
   *
   * The append reaches the server before the queue grows here: `planned_card_ids`
   * is what a resume rebuilds from, so cards added only in React are gone the
   * next time the document is opened. If that call fails the cards are still in
   * the deck -- they just are not in this run, and saying so beats a run that
   * silently forgets them.
   */
  async function addMoreCards(count: number) {
    if (!onGenerateMore || addingCount !== null) return
    setAddingCount(count)
    setAddError(null)
    try {
      const cards = await onGenerateMore(count)
      if (cards.length === 0) {
        setAddError(noCardsNote ?? "No cards came back.")
        return
      }
      if (sessionId) {
        const appended = await appendSessionCards(
          sessionId,
          cards.map((c) => c.id),
        )
        if (appended === null) {
          setAddError("The cards were written but could not join this run. They are in the deck.")
          return
        }
        await reopenSession(sessionId).catch(() => {})
      }
      setCurrentIndex(queue.length)
      setQueue((q) => [...q, ...cards])
      setTotal((t) => t + cards.length)
      setRetryTarget(null)
      setRevealed(false)
      setExplanation("")
      setPredicted(null)
      setGraded(null)
      setCalibration(null)
      setJumpSection(null)
      setSessionState("studying")
    } catch {
      setAddError("Could not write more cards. Is the model reachable?")
    } finally {
      setAddingCount(null)
    }
  }

  if (sessionState === "complete") {
    return (
      <Readout
        mode={mode}
        pending={pending}
        results={results}
        onReAnswer={(cardId) => void reAnswer(cardId)}
        reviewed={reviewed}
        correct={correct}
        predictionsMade={predictionsMade}
        predictionsCalibrated={predictionsCalibrated}
        teachbackAvg={stats.avgScore}
        teachbackDone={stats.completedCount}
        teachbackPassed={stats.passCount}
        onAddMore={onGenerateMore ? addMoreCards : undefined}
        exhaustedNote={exhaustedNote ?? null}
        addingCount={addingCount}
        addError={addError}
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
                <div>
                  {mode === "teachback" && (
                    <p className="mb-1.5 text-xs uppercase tracking-wider text-muted-foreground/70">
                      Expected answer
                    </p>
                  )}
                  <div data-testid="recall-answer">
                    <MarkdownRenderer className={ANSWER_PROSE}>
                      {currentCard.answer}
                    </MarkdownRenderer>
                  </div>
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
              {previousAttempt && (
                <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/30">
                  <p className="text-xs font-semibold uppercase tracking-wider text-amber-800 dark:text-amber-300">
                    Your last attempt -- {previousAttempt.score}/100
                  </p>
                  <div className="mt-2">
                    <InlineTeachbackFeedback result={previousAttempt} />
                  </div>
                  <p className="mt-3 text-xs text-amber-700 dark:text-amber-400">
                    Say it again with that in mind.
                  </p>
                </div>
              )}
              <p className="text-xs uppercase tracking-wider text-muted-foreground/70">
                {previousAttempt ? "Explain it again" : "Explain it in your own words"}
              </p>
              <div className="relative">
                <textarea
                  value={explanation}
                  onChange={(e) => setExplanation(e.target.value)}
                  rows={7}
                  placeholder="Say it the way you would to someone who has not read this."
                  className="w-full resize-y rounded-lg border border-border bg-background p-3 pr-12 text-sm leading-relaxed text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                />
                <VoiceRecordButton
                  size="sm"
                  onTranscribed={(text) => {
                    setExplanation((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text))
                  }}
                  title="Speak your explanation (Whisper)"
                  className="absolute right-2 top-2"
                />
              </div>
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
                <div className="flex flex-col gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-wider text-muted-foreground/70">
                      What you said
                    </p>
                    <blockquote className="mt-1.5 whitespace-pre-wrap border-l-2 border-border pl-3 text-sm italic leading-relaxed text-foreground/80">
                      {/* The API returns user_explanation only once the row is
                          complete, so until then this is the draft as submitted. */}
                      {cardResult?.user_explanation ?? explanation}
                    </blockquote>
                  </div>
                  <TeachbackVerdict
                    result={cardResult}
                    // Per card, not per run: a single failed submission used to mark
                    // every card after it unscored, including the ones that scored.
                    failed={pending.some(
                      (p) => p.flashcardId === currentCard.id && p.id.startsWith("error-"),
                    )}
                  />
                </div>
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
                  {/* Silence is a claim: an answer printed as the expected one,
                      under a quote, reads as verified unless the panel says what
                      was actually checked. */}
                  <p className={`mt-2 text-xs ${sourceNote(currentCard).className}`}>
                    {sourceNote(currentCard).text}
                  </p>
                  {answerCheckNote(currentCard) && (
                    <p className={`mt-0.5 text-xs ${answerCheckNote(currentCard)?.className}`}>
                      {answerCheckNote(currentCard)?.text}
                    </p>
                  )}
                </div>
              )}

              {calibration && (
                <p className={`text-sm font-medium ${CALIBRATION_TEXT_CLASS[calibration.tone]}`}>
                  {calibration.text}
                </p>
              )}

              {mode === "teachback" ? (
                // No grade buttons here. The background evaluator applies an FSRS
                // review of its own once it scores (study.py:1529), so asking for
                // one as well would review the same card twice -- which is what
                // the Study page's teach-back avoids by never offering a grade.
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    data-testid="teachback-next"
                    onClick={() => advance(true)}
                    className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                  >
                    {nextLabel}
                    <ArrowRight size={14} />
                  </button>
                  <button
                    data-testid="teachback-retry"
                    onClick={answerAgain}
                    className="flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
                  >
                    <RotateCcw size={14} />
                    Answer again
                  </button>
                  {!cardResult && (
                    <p className="text-xs text-muted-foreground">
                      Still scoring. Move on -- the verdict is waiting for you at the end of the
                      run.
                    </p>
                  )}
                </div>
              ) : graded ? (
                <button
                  data-testid="recall-next"
                  onClick={() => advance()}
                  className="self-start rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                >
                  {nextLabel}
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
  pending,
  results,
  onReAnswer,
  reviewed,
  correct,
  predictionsMade,
  predictionsCalibrated,
  teachbackAvg,
  teachbackDone,
  teachbackPassed,
  onAddMore,
  exhaustedNote,
  addingCount,
  addError,
  onDone,
}: {
  mode: StudyMode
  pending: PendingTeachback[]
  results: TeachbackResultItem[] | undefined
  onReAnswer: (cardId: string) => void
  reviewed: number
  correct: number
  predictionsMade: number
  predictionsCalibrated: number
  teachbackAvg: number | null
  teachbackDone: number
  teachbackPassed: number
  onAddMore: ((count: number) => Promise<void>) | undefined
  exhaustedNote: string | null
  addingCount: number | null
  addError: string | null
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
          {/* "Got right" counts grades, and a teach-back run gives none -- its
              cards are scored by the evaluator. Reading the grade tally there
              printed "0 of 3" beside a 90/100 average. */}
          {mode === "teachback" ? (
            <Stat
              label="Passed"
              value={teachbackDone === 0 ? "--" : `${teachbackPassed} of ${teachbackDone}`}
            />
          ) : (
            <Stat label="Got right" value={reviewed === 0 ? "--" : `${correct} of ${reviewed}`} />
          )}
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
              {/* No average until every card that stands has one. A mean over
                  the cards that happen to have finished moves as the rest land,
                  and the learner reads the first figure as the run's result. */}
              {teachbackAvg === null
                ? `${teachbackDone} scored so far. The average waits for the rest.`
                : `${teachbackDone} scored, averaging ${teachbackAvg}/100.`}
            </p>
          </div>
        )}
        {mode === "teachback" && teachbackDone === 0 && (
          <p className="text-sm text-muted-foreground">
            No explanation has finished scoring yet. They keep scoring in the background.
          </p>
        )}

        {mode === "teachback" && pending.length > 0 && (
          <TeachbackAttempts pending={pending} results={results} onReAnswer={onReAnswer} />
        )}

        {!onAddMore && exhaustedNote && (
          <p
            data-testid="readout-exhausted"
            className="border-t border-border pt-5 text-sm text-muted-foreground"
          >
            {exhaustedNote}
          </p>
        )}

        {onAddMore && (
          <div className="flex flex-col gap-2 border-t border-border pt-5">
            <p className="text-sm text-muted-foreground">
              Keep going on this document -- new questions join this run rather than
              starting another one.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              {[3, 5, 10].map((n) => (
                <button
                  key={n}
                  data-testid={`readout-add-${n}`}
                  onClick={() => void onAddMore(n)}
                  disabled={addingCount !== null}
                  className="flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
                >
                  {addingCount === n ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Plus size={14} />
                  )}
                  {n} more
                </button>
              ))}
            </div>
            {addError && (
              <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                {addError}
              </p>
            )}
          </div>
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

/**
 * One row per CARD, carrying the explanation that stands -- expanded to what was
 * written, what was expected and how it scored. Moving on while a card is still
 * being evaluated only works if the verdict is still somewhere afterwards.
 *
 * One row per submission put a re-answered card in this list twice, at both its
 * old score and its new one, and the learner had no way to tell which was which.
 */
function TeachbackAttempts({
  pending,
  results,
  onReAnswer,
}: {
  pending: PendingTeachback[]
  results: TeachbackResultItem[] | undefined
  onReAnswer: (cardId: string) => void
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs uppercase tracking-wider text-muted-foreground/70">
        Where each card stands
      </p>
      {standingAttempts(pending).map(({ attempt: p, attemptCount }) => {
        const result = results?.find((r) => r.id === p.id)
        if (!result || result.status !== "complete") {
          return (
            <div
              key={p.id}
              className="flex items-center gap-2 rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground"
            >
              {p.id.startsWith("error-") ? (
                <span>Not scored -- {p.question}</span>
              ) : (
                <>
                  <Loader2 size={13} className="animate-spin" />
                  <span className="line-clamp-1">Still scoring -- {p.question}</span>
                </>
              )}
            </div>
          )
        }
        return (
          <div key={p.id} className="flex flex-col gap-1.5">
            <ExpandableResultRow
              result={result}
              fallbackQuestion={p.question}
              isExpanded={expandedId === p.id}
              onToggle={() => setExpandedId(expandedId === p.id ? null : p.id)}
            />
            <div className="flex items-center gap-3">
              <button
                data-testid="readout-retry"
                // The card, not the question text: two cards can ask nearly the
                // same thing, and a check that compares wording cannot tell that
                // from the same card listed twice.
                data-card-id={p.flashcardId}
                onClick={() => onReAnswer(p.flashcardId)}
                className="flex items-center gap-1.5 self-start text-xs font-medium text-primary hover:underline"
              >
                <RotateCcw size={11} />
                Answer this one again
              </button>
              {attemptCount > 1 && (
                // The replaced score is gone from the summary, but the fact of
                // it is not: a 45 that arrived after a 10 is a different thing
                // from a 45 first time.
                <span className="text-xs text-muted-foreground">
                  Attempt {attemptCount}
                </span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
