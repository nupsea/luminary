/**
 * StudySession -- full-screen flashcard review with Framer Motion flip animation.
 *
 * This component handles ONLY flashcard review (FSRS ratings).
 * Teach-back sessions are handled by TeachbackSession.tsx.
 *
 * Props:
 *   documentId   -- optional document scope for GET /study/due
 *   collectionId -- optional collection scope
 *   filters      -- optional tag/document_ids/note_ids
 *   onExit       -- callback invoked after session ends
 */

import { AnimatePresence, motion } from "framer-motion"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import {
  Check,
  ChevronDown,
  ChevronsUp,
  ChevronUp,
  ExternalLink,
  Loader2,
  Minus,
  RotateCcw,
  X as XIcon,
  Zap,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { ClozeCard } from "@/components/ClozeCard"
import {
  useStudySession,
  type UseStudySessionInput,
} from "@/hooks/useStudySession"
import {
  type Flashcard,
  type Rating,
  type SourceContext,
  submitReview,
  fetchSourceContext,
} from "@/lib/studyApi"
import { apiGet } from "@/lib/apiClient"
import { useAppStore } from "@/store"

// SourceContextPanel

interface SourceContextPanelProps {
  context: SourceContext
  onDismiss: () => void
  onOpenInReader: () => void
}

function SourceContextPanel({ context, onDismiss, onOpenInReader }: SourceContextPanelProps) {
  const [expanded, setExpanded] = useState(true)
  const navigate = useNavigate()

  function openInReader() {
    onOpenInReader()
    const params = new URLSearchParams()
    params.set("doc", context.document_id)
    params.set("section_id", context.section_id)
    if (context.pdf_page_number != null) {
      params.set("page", String(context.pdf_page_number))
    }
    navigate(`/library?${params.toString()}`, { state: { from: "/study" } })
  }

  return (
    <div className="w-full max-w-2xl rounded-lg border border-border bg-muted/30">
      <div className="flex items-center justify-between px-4 py-2">
        <button
          onClick={() => setExpanded((e) => !e)}
          className="flex flex-1 items-center gap-2 text-left text-xs font-semibold text-muted-foreground hover:text-foreground"
        >
          Source passage
          {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>
        <button
          onClick={onDismiss}
          className="ml-2 rounded p-0.5 text-muted-foreground hover:text-foreground"
          aria-label="Dismiss source panel"
        >
          <XIcon size={13} />
        </button>
      </div>

      {expanded && (
        <div className="flex flex-col gap-3 px-4 pb-4">
          {context.section_preview ? (
            <blockquote className="border-l-2 border-border pl-3 text-xs text-muted-foreground italic">
              {context.section_preview.length >= 400
                ? `${context.section_preview}...`
                : context.section_preview}
            </blockquote>
          ) : (
            <p className="text-xs text-muted-foreground">No preview available for this section.</p>
          )}
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground">
              {context.section_heading} -- {context.document_title}
            </span>
            <button
              onClick={openInReader}
              className="flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs text-foreground hover:bg-accent"
            >
              <ExternalLink size={10} />
              Open in reader
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// SourcePanel

// Local: a 7-field projection of WebReferenceItem with `source_quality`
// narrowed to a literal union for the QUALITY_LABEL badge map below.
// Aliasing to the generated schema would relax that to `string` and
// break the indexed lookup.

type SourceQuality = "official_docs" | "spec" | "wiki" | "tutorial" | "blog" | "unknown"

interface WebRef {
  id: string
  term: string
  url: string
  title: string
  source_quality: SourceQuality
  is_llm_suggested: boolean
  is_outdated: boolean
}

interface SectionReferencesResponse {
  section_id: string
  references: WebRef[]
}

const QUALITY_LABEL: Record<SourceQuality, string> = {
  official_docs: "Official",
  spec: "Spec",
  wiki: "Wiki",
  tutorial: "Tutorial",
  blog: "Blog",
  unknown: "Unknown",
}

const QUALITY_CLASS: Record<SourceQuality, string> = {
  official_docs: "bg-green-100 text-green-800 dark:bg-green-950/40 dark:text-green-300",
  spec: "bg-blue-100 text-blue-800 dark:bg-blue-950/40 dark:text-blue-300",
  wiki: "bg-gray-100 text-gray-800 dark:bg-gray-800/60 dark:text-gray-300",
  tutorial: "bg-gray-100 text-gray-700 dark:bg-gray-800/60 dark:text-gray-300",
  blog: "bg-gray-100 text-gray-600 dark:bg-gray-800/60 dark:text-gray-400",
  unknown: "bg-gray-100 text-gray-500 dark:bg-gray-800/60 dark:text-gray-400",
}

function SourcePanel({ card }: { card: Flashcard }) {
  const [expanded, setExpanded] = useState(true)

  const { data, isLoading, isError } = useQuery<SectionReferencesResponse>({
    queryKey: ["section-references", card.section_id],
    queryFn: () => {
      if (!card.section_id) return Promise.resolve({ section_id: "", references: [] })
      return apiGet<SectionReferencesResponse>(
        `/references/sections/${card.section_id}`,
      )
    },
    enabled: !!card.section_id,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  })

  return (
    <div className="w-full max-w-2xl rounded-lg border border-border bg-muted/30">
      <button
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center justify-between px-4 py-2 text-left text-xs font-semibold text-muted-foreground hover:text-foreground"
      >
        Source
        {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>

      {expanded && (
        <div className="flex flex-col gap-3 px-4 pb-4">
          {card.source_excerpt && (
            <blockquote className="border-l-2 border-border pl-3 text-xs text-muted-foreground italic">
              {card.source_excerpt}
            </blockquote>
          )}

          {!card.section_id ? (
            <p className="text-xs text-muted-foreground">No web references for this card.</p>
          ) : isLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 size={12} className="animate-spin" />
              Loading references...
            </div>
          ) : isError ? (
            <p className="text-xs text-amber-700">Source references unavailable.</p>
          ) : (data?.references ?? []).length === 0 ? (
            <p className="text-xs text-muted-foreground">No web references for this section yet.</p>
          ) : (
            <div className="flex flex-col gap-1.5">
              {(data?.references ?? []).slice(0, 5).map((ref) => (
                <a
                  key={ref.id}
                  href={ref.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 rounded border border-border px-2 py-1 text-xs hover:bg-accent"
                >
                  <ExternalLink size={10} className="shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate font-medium text-primary">
                    {ref.title}
                  </span>
                  <span
                    className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${QUALITY_CLASS[ref.source_quality]}`}
                  >
                    {QUALITY_LABEL[ref.source_quality]}
                  </span>
                  {ref.is_llm_suggested && (
                    <span className="shrink-0 rounded bg-amber-100 px-1 text-[10px] font-medium text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                      ~
                    </span>
                  )}
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Rating buttons

// Each grade also carries a distinct icon so Again/Good aren't told apart by hue
// alone (red-green color-vision deficiency is the most common case).
const RATINGS: { label: string; value: Rating; className: string; icon: LucideIcon }[] = [
  { label: "Again", value: "again", icon: RotateCcw, className: "bg-red-100 text-red-700 border-red-200 hover:bg-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900 dark:hover:bg-red-900/50" },
  { label: "Hard", value: "hard", icon: Minus, className: "bg-orange-100 text-orange-700 border-orange-200 hover:bg-orange-200 dark:bg-orange-950/40 dark:text-orange-300 dark:border-orange-900 dark:hover:bg-orange-900/50" },
  { label: "Good", value: "good", icon: Check, className: "bg-green-100 text-green-700 border-green-200 hover:bg-green-200 dark:bg-green-950/40 dark:text-green-300 dark:border-green-900 dark:hover:bg-green-900/50" },
  { label: "Easy", value: "easy", icon: ChevronsUp, className: "bg-blue-100 text-blue-700 border-blue-200 hover:bg-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-900 dark:hover:bg-blue-900/50" },
]

// Progress bar

function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total === 0 ? 0 : Math.round((done / total) * 100)
  return (
    <div className="w-full max-w-2xl">
      <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
        <span>{done} of {total} reviewed</span>
        <span>{pct}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
        <div
          className="h-full rounded-full bg-primary transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

// FlashCard (flippable)

interface FlashCardProps {
  card: Flashcard
  showAnswer: boolean
  onFlip?: () => void
}

function FlashCard({ card, showAnswer, onFlip }: FlashCardProps) {
  // Card grows to fit its content -- long answers used to overflow a fixed-height
  // 3D-flip container and overlap the rating buttons below. We reveal the answer
  // beneath the question (Anki-style) and left-align it so multi-point answers
  // and markdown bullets read cleanly.
  return (
    <div
      className="w-full max-w-2xl cursor-pointer rounded-xl border border-border bg-card p-8 shadow-md transition-shadow hover:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      onClick={onFlip}
      role="button"
      tabIndex={0}
      aria-label={showAnswer ? "Flashcard answer, press Enter to show question" : "Flashcard question, press Enter to reveal answer"}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          // Stop the event before it reaches the session-level window listener,
          // which would otherwise also fire.
          e.stopPropagation()
          onFlip?.()
        }
      }}
    >
      {!showAnswer ? (
        <div className="flex min-h-48 items-center justify-center">
          <MarkdownRenderer className="text-center text-xl font-semibold text-foreground">
            {card.question}
          </MarkdownRenderer>
        </div>
      ) : (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2 }}
          className="flex flex-col gap-4"
        >
          <MarkdownRenderer className="text-center text-sm text-muted-foreground">
            {card.question}
          </MarkdownRenderer>
          <hr className="border-border" />
          <MarkdownRenderer className="text-left text-base leading-relaxed text-foreground prose-p:my-2 prose-ul:my-2 prose-li:my-0.5">
            {card.answer}
          </MarkdownRenderer>
        </motion.div>
      )}
    </div>
  )
}

// SessionComplete screen

interface SessionCompleteProps {
  reviewed: number
  correct: number
  predictionsMade: number
  predictionsCalibrated: number
  nextReviewDate: string | null
  onBack: () => void
  onStartNext: () => void
}

function SessionComplete({ reviewed, correct, predictionsMade, predictionsCalibrated, nextReviewDate, onBack, onStartNext }: SessionCompleteProps) {
  const pct = reviewed === 0 ? 0 : Math.round((correct / reviewed) * 100)

  return (
    <div className="flex flex-col items-center gap-6 px-4 py-6">
      <div className="flex flex-col items-center gap-2">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-900/30">
          <Zap size={28} className="text-blue-600 dark:text-blue-400" />
        </div>
        <h2 className="text-2xl font-bold text-foreground">Session Complete!</h2>
      </div>

      <div className="flex gap-8 text-center">
        <div className="flex flex-col items-center">
          <span className="text-3xl font-bold text-foreground">{reviewed}</span>
          <span className="text-sm text-muted-foreground">Cards reviewed</span>
        </div>
        <div className="flex flex-col items-center">
          <span className="text-3xl font-bold text-foreground">{pct}%</span>
          <span className="text-sm text-muted-foreground">Accuracy</span>
        </div>
      </div>

      {predictionsMade > 0 && (
        <p className="text-sm text-muted-foreground">
          Calibration this session:{" "}
          <span className="font-medium text-foreground">
            {predictionsCalibrated} of {predictionsMade}
          </span>{" "}
          prediction{predictionsMade === 1 ? "" : "s"} matched
        </p>
      )}

      {nextReviewDate && (
        <p className="text-sm text-muted-foreground">
          Next review:{" "}
          <span className="font-medium text-foreground">
            {new Date(nextReviewDate).toLocaleDateString()}
          </span>
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={onStartNext}
          className="rounded-lg bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Start Next Set
        </button>
        <button
          onClick={onBack}
          className="rounded-lg border border-border px-6 py-2 text-sm font-medium text-muted-foreground hover:bg-accent"
        >
          Back to Study
        </button>
      </div>
    </div>
  )
}

function getSessionPhase(index: number, total: number): { label: string; style: string } {
  if (total <= 3) return { label: "Review", style: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400" }
  const pct = index / total
  if (pct < 0.25) return { label: "Warm-up", style: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400" }
  if (pct < 0.85) return { label: "Engage", style: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400" }
  return { label: "Reflect", style: "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400" }
}

// Calibration feedback -- compares the learner's pre-reveal prediction (3-point:
// Know it / Unsure / Blank, encoded as good / hard / again) against the grade they
// actually gave after seeing the answer (4-point FSRS). "calibrated" means the two
// land in the same confidence bucket; the copy nudges over/under-confidence.
type CalibrationTone = "positive" | "warn" | "info" | "neutral"

function ratingBucket(r: Rating): "knew" | "unsure" | "blank" {
  if (r === "good" || r === "easy") return "knew"
  if (r === "hard") return "unsure"
  return "blank"
}

function calibrationMessage(
  predicted: Rating,
  actual: Rating,
): { text: string; tone: CalibrationTone; calibrated: boolean } {
  const p = ratingBucket(predicted)
  const a = ratingBucket(actual)
  if (p === a) return { text: "Well calibrated.", tone: "positive", calibrated: true }
  const order = { blank: 0, unsure: 1, knew: 2 } as const
  if (order[p] > order[a]) {
    return { text: "Overconfident — you predicted you knew it.", tone: "warn", calibrated: false }
  }
  return { text: "You knew more than you thought.", tone: "info", calibrated: false }
}

const CALIBRATION_TEXT_CLASS: Record<CalibrationTone, string> = {
  positive: "text-emerald-600 dark:text-emerald-400",
  warn: "text-amber-600 dark:text-amber-400",
  info: "text-blue-600 dark:text-blue-400",
  neutral: "text-muted-foreground",
}

// StudySession -- main component (flashcard-only)

interface StudySessionProps {
  initial: UseStudySessionInput["initial"]
  scopeForBeginNew: UseStudySessionInput["scopeForBeginNew"]
  onExit: () => void
}

export const FLASHCARD_CARD_LIMIT = 50

export function StudySession({ initial, scopeForBeginNew, onExit }: StudySessionProps) {
  const {
    sessionState,
    sessionId,
    queue,
    currentIndex,
    reviewed,
    total,
    setCurrentIndex,
    setReviewed,
    completeSession,
    exit,
    beginNew,
  } = useStudySession({ initial, scopeForBeginNew })

  // `showAnswer` = which card face is displayed (the flip). `revealed` = a
  // one-way latch, set once the learner commits to seeing the answer (predict or
  // skip). Controls key off `revealed` so flipping the card back to the question
  // no longer regresses to the confidence picker -- the rating buttons stay put.
  const [showAnswer, setShowAnswer] = useState(false)
  const [revealed, setRevealed] = useState(false)
  const [correct, setCorrect] = useState(0)
  const [isRating, setIsRating] = useState(false)
  const [lastRating, setLastRating] = useState<Rating | null>(null)
  const [predictedRating, setPredictedRating] = useState<Rating | null>(null)
  const [nextReviewDate, setNextReviewDate] = useState<string | null>(null)
  const [sourceContext, setSourceContext] = useState<SourceContext | null>(null)
  const [sourceContextLoading, setSourceContextLoading] = useState(false)
  const dismissedSourceContextIds = useRef(new Set<string>())
  // Calibration: feedback shown inline on the cards that already pause (again/hard),
  // plus per-session tallies surfaced on the completion screen.
  const [calibrationInline, setCalibrationInline] = useState<{ text: string; tone: CalibrationTone } | null>(null)
  const [predictionsMade, setPredictionsMade] = useState(0)
  const [predictionsCalibrated, setPredictionsCalibrated] = useState(0)

  async function handleRate(rating: Rating) {
    if (!sessionId || isRating) return
    const card = queue[currentIndex]
    if (!card) return

    setIsRating(true)

    try {
      await submitReview(card.id, rating, sessionId, predictedRating ?? undefined)
      const isCorrect = rating !== "again"
      setReviewed((r) => r + 1)
      setCorrect((c) => c + (isCorrect ? 1 : 0))

      if (card.due_date && (!nextReviewDate || card.due_date < nextReviewDate)) {
        setNextReviewDate(card.due_date)
      }

      setLastRating(rating)

      // Calibration: only when the learner made a prediction this card. Surface it
      // inline on the again/hard cards (which already pause for a source panel) and
      // as a non-blocking toast on the good/easy fast path so the loop stays quick.
      if (predictedRating !== null) {
        const cal = calibrationMessage(predictedRating, rating)
        setPredictionsMade((n) => n + 1)
        if (cal.calibrated) setPredictionsCalibrated((n) => n + 1)
        if (rating === "again" || rating === "hard") {
          setCalibrationInline({ text: cal.text, tone: cal.tone })
        } else {
          const notify =
            cal.tone === "positive" ? toast.success : cal.tone === "warn" ? toast.warning : toast.info
          notify(cal.text)
        }
      }

      // A session answers each planned card exactly once. "again" means FSRS
      // reschedules the card for a future session -- not that we re-queue it
      // inline here, which would inflate the session beyond the planned size.

      // Source context / SourcePanel flow only applies to regular (non-cloze) cards.
      // Cloze cards always advance immediately — the source panels live in the else
      // branch and are never rendered while a cloze card is active.
      const isCloze = card.flashcard_type === "cloze"

      if (!isCloze && (rating === "again" || rating === "hard")) {
        if (!dismissedSourceContextIds.current.has(card.id)) {
          setSourceContextLoading(true)
          const ctx = await fetchSourceContext(card.id)
          setSourceContextLoading(false)
          if (ctx !== null) {
            setSourceContext(ctx)
            return
          }
        }
        if (rating === "hard") {
          const nextIdx = currentIndex + 1
          if (nextIdx >= queue.length) {
            await completeSession()
          } else {
            setCurrentIndex(nextIdx)
            setShowAnswer(false)
            setRevealed(false)
            setLastRating(null)
            setPredictedRating(null)
          }
        }
        return
      }

      // Advance immediately: cloze cards (all ratings) + regular cards ("good"/"easy")
      const nextIdx = currentIndex + 1
      if (nextIdx >= queue.length) {
        await completeSession()
      } else {
        setCurrentIndex(nextIdx)
        setShowAnswer(false)
        setRevealed(false)
        setLastRating(null)
        setPredictedRating(null)
      }
    } finally {
      setIsRating(false)
    }
  }

  async function advanceCard() {
    setSourceContext(null)
    setSourceContextLoading(false)
    setCalibrationInline(null)
    const nextIdx = currentIndex + 1
    if (nextIdx >= queue.length) {
      await completeSession()
    } else {
      setCurrentIndex(nextIdx)
      setShowAnswer(false)
      setRevealed(false)
      setLastRating(null)
      setPredictedRating(null)
    }
  }

  function handleDismissSourceContext() {
    const card = queue[currentIndex]
    if (card) dismissedSourceContextIds.current.add(card.id)
    void advanceCard()
  }

  function handleBackToStudy() {
    void exit(onExit)
  }

  // Keyboard control for the standard flashcard flow: Space/Enter flips (skipping
  // the prediction), 1-4 grade once the answer is shown, Enter/Space continues past
  // a source panel, and Esc ends. Cloze cards own their own keys, so we no-op there.
  useEffect(() => {
    function isTypingTarget(t: EventTarget | null): boolean {
      if (!(t instanceof HTMLElement)) return false
      if (t.isContentEditable) return true
      const tag = t.tagName
      return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT"
    }
    function onKeyDown(e: KeyboardEvent) {
      if (isTypingTarget(e.target)) return
      if (e.key === "Escape") {
        e.preventDefault()
        void exit(onExit)
        return
      }
      const card = queue[currentIndex]
      if (!card) return
      // A source/continue panel is open: Enter or Space advances.
      if (sourceContext !== null) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          void advanceCard()
        }
        return
      }
      if (isRating) return
      const isClozeCard =
        card.flashcard_type === "cloze" &&
        card.cloze_text !== null &&
        /\{\{.+?\}\}/.test(card.cloze_text)
      if (isClozeCard) return
      if (!revealed) {
        if (e.key === " " || e.key === "Enter") {
          e.preventDefault()
          setRevealed(true)
          setShowAnswer(true)
          return
        }
        // 1-3 record the confidence prediction (Blank / Unsure / Know it), then reveal.
        // Ordered worst->best to match the 1-4 grade keys shown after the reveal.
        const predict: Record<string, Rating> = { "1": "again", "2": "hard", "3": "good" }
        const predicted = predict[e.key]
        if (predicted) {
          e.preventDefault()
          setPredictedRating(predicted)
          setRevealed(true)
          setShowAnswer(true)
        }
        return
      }
      if (lastRating === null) {
        const grade: Record<string, Rating> = { "1": "again", "2": "hard", "3": "good", "4": "easy" }
        const rating = grade[e.key]
        if (rating) {
          e.preventDefault()
          void handleRate(rating)
        } else if (e.key === " " || e.key === "Enter") {
          // after the reveal, Space/Enter flips the face to peek at the question
          e.preventDefault()
          setShowAnswer((prev) => !prev)
        }
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queue, currentIndex, showAnswer, revealed, lastRating, isRating, sourceContext, onExit])

  if (sessionState === "loading") {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 size={32} className="animate-spin text-primary" />
      </div>
    )
  }

  if (sessionState === "empty") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
        <Zap size={40} className="text-muted-foreground/40" />
        <p className="text-sm text-muted-foreground">No cards due for review right now.</p>
        <button
          onClick={onExit}
          className="rounded-lg border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-accent"
        >
          Back to Study
        </button>
      </div>
    )
  }

  if (sessionState === "complete") {
    return (
      <div className="flex h-full items-start justify-center overflow-auto py-8">
        <SessionComplete
          reviewed={reviewed}
          correct={correct}
          nextReviewDate={nextReviewDate}
          predictionsMade={predictionsMade}
          predictionsCalibrated={predictionsCalibrated}
          onBack={() => void exit(onExit)}
          onStartNext={() => {
            setCorrect(0)
            setLastRating(null)
            setPredictedRating(null)
            setShowAnswer(false)
            setRevealed(false)
            setNextReviewDate(null)
            setSourceContext(null)
            setCalibrationInline(null)
            // Calibration is the moat metric — carry it across sets so it never
            // silently resets to zero when the learner continues into a new set.
            dismissedSourceContextIds.current.clear()
            void beginNew()
          }}
        />
      </div>
    )
  }

  const currentCard = queue[currentIndex]
  if (!currentCard) return null

  const sessionPhase = getSessionPhase(currentIndex, queue.length)

  return (
    <div className="flex h-full flex-col items-center gap-6 overflow-auto bg-background px-6 py-8">
      {/* Header */}
      <div className="flex w-full max-w-2xl items-center justify-between">
        <div className="flex items-center gap-2">
          <Zap size={18} className="text-blue-500" />
          <span className="text-sm font-semibold text-blue-600 dark:text-blue-400">
            Flashcard Review
          </span>
          <span className={`ml-1 rounded-full px-2 py-0.5 text-xs font-medium ${sessionPhase.style}`}>
            {sessionPhase.label}
          </span>
        </div>
        <span className="rounded-full bg-blue-100 px-3 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
          Card {currentIndex + 1} of {queue.length}
        </span>
      </div>

      <ProgressBar done={reviewed} total={total} />

      {/* dispatch to ClozeCard for cloze flashcard_type */}
      {currentCard.flashcard_type === "cloze" &&
      currentCard.cloze_text !== null &&
      /\{\{.+?\}\}/.test(currentCard.cloze_text) ? (
        <AnimatePresence mode="wait">
          <motion.div
            key={currentCard.id}
            initial={{ x: 300, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: -300, opacity: 0 }}
            transition={{ duration: 0.25, ease: "easeInOut" }}
            className="w-full max-w-2xl"
          >
            <ClozeCard card={currentCard} onRate={handleRate} isRating={isRating} />
          </motion.div>
        </AnimatePresence>
      ) : (
        <>
          <AnimatePresence mode="wait">
            <motion.div
              key={currentCard.id}
              initial={{ x: 300, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: -300, opacity: 0 }}
              transition={{ duration: 0.25, ease: "easeInOut" }}
              className="w-full max-w-2xl"
            >
              <FlashCard
                card={currentCard}
                showAnswer={showAnswer}
                onFlip={() => {
                  // First interaction reveals the answer (and commits to grading);
                  // afterwards a click just flips the face to peek at the question.
                  if (!revealed) {
                    setRevealed(true)
                    setShowAnswer(true)
                  } else {
                    setShowAnswer((prev) => !prev)
                  }
                }}
              />
            </motion.div>
          </AnimatePresence>

          {!revealed ? (
            <div className="flex flex-col items-center gap-3">
              <p className="text-xs text-muted-foreground">How confident are you?</p>
              <div className="flex gap-2">
                {(
                  [
                    { label: "Blank", value: "again" as Rating },
                    { label: "Unsure", value: "hard" as Rating },
                    { label: "Know it", value: "good" as Rating },
                  ] as const
                ).map(({ label, value }, i) => (
                  <button
                    key={value}
                    onClick={() => {
                      setPredictedRating(value)
                      setRevealed(true)
                      setShowAnswer(true)
                    }}
                    className={`rounded border px-4 py-1.5 text-xs font-medium transition-colors ${
                      predictedRating === value
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-background text-muted-foreground hover:bg-accent"
                    }`}
                  >
                    <span className="mr-1.5 opacity-50">{i + 1}</span>
                    {label}
                  </button>
                ))}
              </div>
              <button
                onClick={() => {
                  setRevealed(true)
                  setShowAnswer(true)
                }}
                className="text-xs text-muted-foreground underline-offset-2 hover:underline"
              >
                Skip prediction → Show Answer
              </button>
              <p className="text-[11px] text-muted-foreground">1–3 to predict · Space to skip</p>
            </div>
          ) : lastRating === null ? (
            <div className="flex flex-col items-center gap-2">
              <div className="flex gap-3">
                {RATINGS.map(({ label, value, className, icon: Icon }, i) => (
                  <button
                    key={value}
                    onClick={() => void handleRate(value)}
                    disabled={isRating}
                    aria-label={`${label} (press ${i + 1})`}
                    className={`flex items-center gap-1.5 rounded border px-5 py-2.5 text-sm font-medium transition-colors disabled:opacity-50 ${className}`}
                  >
                    <span className="opacity-50">{i + 1}</span>
                    <Icon size={14} aria-hidden />
                    {label}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-muted-foreground">Space to flip · 1–4 to rate · Esc to end</p>
            </div>
          ) : null}

          {calibrationInline && (
            <p className={`text-sm font-medium ${CALIBRATION_TEXT_CLASS[calibrationInline.tone]}`}>
              {calibrationInline.text}
            </p>
          )}

          {/* Source context panel */}
          {(lastRating === "again" || lastRating === "hard") && sourceContextLoading && (
            <div className="w-full max-w-2xl rounded-lg border border-border bg-muted/30 p-4">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 size={12} className="animate-spin" />
                Loading source passage...
              </div>
            </div>
          )}

          {sourceContext !== null && (
            <>
              <SourceContextPanel
                context={sourceContext}
                onDismiss={handleDismissSourceContext}
                onOpenInReader={() => {
                  if (sessionId) {
                    useAppStore.getState().setPendingStudyResume({
                      sessionId,
                      mode: scopeForBeginNew.mode,
                    })
                  }
                }}
              />
              <button
                onClick={() => void advanceCard()}
                className="rounded-lg bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                Continue
              </button>
            </>
          )}

          {lastRating === "again" && sourceContext === null && !sourceContextLoading && (
            <>
              <SourcePanel card={currentCard} />
              <button
                onClick={() => void advanceCard()}
                className="rounded-lg bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                Continue
              </button>
            </>
          )}
        </>
      )}

      <button
        onClick={() => void handleBackToStudy()}
        className="text-xs text-muted-foreground hover:text-foreground"
      >
        End session
      </button>
    </div>
  )
}
