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
import { useRef, useState } from "react"
import {
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Loader2,
  X as XIcon,
  Zap,
} from "lucide-react"
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
import { API_BASE } from "@/lib/config"

// ---------------------------------------------------------------------------
// S155: SourceContextPanel
// ---------------------------------------------------------------------------

interface SourceContextPanelProps {
  context: SourceContext
  onDismiss: () => void
}

function SourceContextPanel({ context, onDismiss }: SourceContextPanelProps) {
  const [expanded, setExpanded] = useState(true)

  function buildReaderUrl(): string {
    const params = new URLSearchParams()
    params.set("doc", context.document_id)
    params.set("section_id", context.section_id)
    if (context.pdf_page_number != null) {
      params.set("page", String(context.pdf_page_number))
    }
    return `/?${params.toString()}`
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
            <a
              href={buildReaderUrl()}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs text-foreground hover:bg-accent"
            >
              <ExternalLink size={10} />
              Open in reader
            </a>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// S138: SourcePanel
// ---------------------------------------------------------------------------

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
  official_docs: "bg-green-100 text-green-800",
  spec: "bg-blue-100 text-blue-800",
  wiki: "bg-gray-100 text-gray-800",
  tutorial: "bg-gray-100 text-gray-700",
  blog: "bg-gray-100 text-gray-600",
  unknown: "bg-gray-100 text-gray-500",
}

function SourcePanel({ card }: { card: Flashcard }) {
  const [expanded, setExpanded] = useState(true)

  const { data, isLoading, isError } = useQuery<SectionReferencesResponse>({
    queryKey: ["section-references", card.section_id],
    queryFn: async () => {
      if (!card.section_id) return { section_id: "", references: [] }
      const res = await fetch(`${API_BASE}/references/sections/${card.section_id}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.json() as Promise<SectionReferencesResponse>
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
                    <span className="shrink-0 rounded bg-amber-100 px-1 text-[10px] font-medium text-amber-700">
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

// ---------------------------------------------------------------------------
// Rating buttons
// ---------------------------------------------------------------------------

const RATINGS: { label: string; value: Rating; className: string }[] = [
  { label: "Again", value: "again", className: "bg-red-100 text-red-700 border-red-200 hover:bg-red-200" },
  { label: "Hard", value: "hard", className: "bg-orange-100 text-orange-700 border-orange-200 hover:bg-orange-200" },
  { label: "Good", value: "good", className: "bg-green-100 text-green-700 border-green-200 hover:bg-green-200" },
  { label: "Easy", value: "easy", className: "bg-blue-100 text-blue-700 border-blue-200 hover:bg-blue-200" },
]

// ---------------------------------------------------------------------------
// Progress bar
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// FlashCard (flippable)
// ---------------------------------------------------------------------------

interface FlashCardProps {
  card: Flashcard
  showAnswer: boolean
  onFlip?: () => void
}

function FlashCard({ card, showAnswer, onFlip }: FlashCardProps) {
  return (
    <div
      className="relative min-h-64 w-full max-w-2xl cursor-pointer"
      style={{ perspective: "1000px", position: "relative" }}
      onClick={onFlip}
    >
      <motion.div
        className="absolute flex min-h-64 w-full flex-col items-center justify-center overflow-auto rounded-xl border border-border bg-card p-8 text-center shadow-md"
        animate={{ rotateY: showAnswer ? -180 : 0 }}
        transition={{ duration: 0.4, ease: "easeInOut" }}
        style={{ backfaceVisibility: "hidden" }}
      >
        <MarkdownRenderer className="text-xl font-semibold text-foreground">{card.question}</MarkdownRenderer>
      </motion.div>

      <motion.div
        className="absolute flex min-h-64 w-full flex-col items-center justify-center gap-4 overflow-auto rounded-xl border border-border bg-card p-8 text-center shadow-md"
        initial={{ rotateY: 180 }}
        animate={{ rotateY: showAnswer ? 0 : 180 }}
        transition={{ duration: 0.4, ease: "easeInOut" }}
        style={{ backfaceVisibility: "hidden" }}
      >
        <MarkdownRenderer className="text-sm text-muted-foreground">{card.question}</MarkdownRenderer>
        <hr className="w-3/4 border-border" />
        <MarkdownRenderer className="text-lg font-medium text-foreground">{card.answer}</MarkdownRenderer>
      </motion.div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SessionComplete screen
// ---------------------------------------------------------------------------

interface SessionCompleteProps {
  reviewed: number
  correct: number
  nextReviewDate: string | null
  onBack: () => void
  onStartNext: () => void
}

function SessionComplete({ reviewed, correct, nextReviewDate, onBack, onStartNext }: SessionCompleteProps) {
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
          <span className={`text-3xl font-bold ${pct >= 60 ? "text-green-600" : "text-amber-600"}`}>{pct}%</span>
          <span className="text-sm text-muted-foreground">Correct</span>
        </div>
      </div>

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

// ---------------------------------------------------------------------------
// StudySession -- main component (flashcard-only)
// ---------------------------------------------------------------------------

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

  const [showAnswer, setShowAnswer] = useState(false)
  const [correct, setCorrect] = useState(0)
  const [isRating, setIsRating] = useState(false)
  const [lastRating, setLastRating] = useState<Rating | null>(null)
  const [nextReviewDate, setNextReviewDate] = useState<string | null>(null)
  const [sourceContext, setSourceContext] = useState<SourceContext | null>(null)
  const [sourceContextLoading, setSourceContextLoading] = useState(false)
  const dismissedSourceContextIds = useRef(new Set<string>())

  async function handleRate(rating: Rating) {
    if (!sessionId || isRating) return
    const card = queue[currentIndex]
    if (!card) return

    setIsRating(true)

    try {
      await submitReview(card.id, rating, sessionId)
      const isCorrect = rating !== "again"
      setReviewed((r) => r + 1)
      setCorrect((c) => c + (isCorrect ? 1 : 0))

      if (card.due_date && (!nextReviewDate || card.due_date < nextReviewDate)) {
        setNextReviewDate(card.due_date)
      }

      setLastRating(rating)

      // A session answers each planned card exactly once. "again" means FSRS
      // reschedules the card for a future session -- not that we re-queue it
      // inline here, which would inflate the session beyond the planned size.

      // S155: lazy-fetch source context after "again" or "hard"
      if (rating === "again" || rating === "hard") {
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
            setLastRating(null)
          }
        }
        return
      }

      // "good" / "easy": advance immediately
      const nextIdx = currentIndex + 1
      if (nextIdx >= queue.length) {
        await completeSession()
      } else {
        setCurrentIndex(nextIdx)
        setShowAnswer(false)
        setLastRating(null)
      }
    } finally {
      setIsRating(false)
    }
  }

  async function advanceCard() {
    setSourceContext(null)
    setSourceContextLoading(false)
    const nextIdx = currentIndex + 1
    if (nextIdx >= queue.length) {
      await completeSession()
    } else {
      setCurrentIndex(nextIdx)
      setShowAnswer(false)
      setLastRating(null)
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
          onBack={() => void exit(onExit)}
          onStartNext={() => {
            setCorrect(0)
            setLastRating(null)
            setShowAnswer(false)
            setNextReviewDate(null)
            setSourceContext(null)
            dismissedSourceContextIds.current.clear()
            void beginNew()
          }}
        />
      </div>
    )
  }

  const currentCard = queue[currentIndex]
  if (!currentCard) return null

  return (
    <div className="flex h-full flex-col items-center gap-6 overflow-auto bg-background px-6 py-8">
      {/* Header */}
      <div className="flex w-full max-w-2xl items-center justify-between">
        <div className="flex items-center gap-2">
          <Zap size={18} className="text-blue-500" />
          <span className="text-sm font-semibold text-blue-600 dark:text-blue-400">
            Flashcard Review
          </span>
        </div>
        <span className="rounded-full bg-blue-100 px-3 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
          Card {currentIndex + 1} of {queue.length}
        </span>
      </div>

      <ProgressBar done={reviewed} total={total} />

      {/* S154: dispatch to ClozeCard for cloze flashcard_type */}
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
                onFlip={() => setShowAnswer((prev) => !prev)}
              />
            </motion.div>
          </AnimatePresence>

          {!showAnswer ? (
            <button
              onClick={() => setShowAnswer(true)}
              className="rounded-lg bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Show Answer
            </button>
          ) : lastRating === null ? (
            <div className="flex gap-3">
              {RATINGS.map(({ label, value, className }) => (
                <button
                  key={value}
                  onClick={() => void handleRate(value)}
                  disabled={isRating}
                  className={`rounded border px-5 py-2.5 text-sm font-medium transition-colors disabled:opacity-50 ${className}`}
                >
                  {label}
                </button>
              ))}
            </div>
          ) : null}

          {/* S155: Source context panel */}
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
              <SourceContextPanel context={sourceContext} onDismiss={handleDismissSourceContext} />
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
