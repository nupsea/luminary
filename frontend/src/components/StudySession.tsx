/**
 * StudySession — full-screen flashcard review with Framer Motion flip animation.
 *
 * Props:
 *   documentId   — optional document scope for GET /study/due
 *   onExit       — callback invoked after POST /study/sessions/{id}/end
 */

import { AnimatePresence, motion } from "framer-motion"
import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"

const API_BASE = "http://localhost:8000"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Flashcard {
  id: string
  question: string
  answer: string
  due_date: string | null
}

type Rating = "again" | "hard" | "good" | "easy"

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function startSession(documentId: string | null): Promise<string> {
  const res = await fetch(`${API_BASE}/study/sessions/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId, mode: "flashcard" }),
  })
  if (!res.ok) throw new Error("Failed to start session")
  const data = (await res.json()) as { id: string }
  return data.id
}

async function fetchDueCards(documentId: string | null): Promise<Flashcard[]> {
  const params = new URLSearchParams({ limit: "20" })
  if (documentId) params.set("document_id", documentId)
  const res = await fetch(`${API_BASE}/study/due?${params.toString()}`)
  if (!res.ok) return []
  return res.json() as Promise<Flashcard[]>
}

async function submitReview(
  cardId: string,
  rating: Rating,
  sessionId: string,
): Promise<void> {
  await fetch(`${API_BASE}/flashcards/${cardId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating, session_id: sessionId }),
  })
}

async function endSession(sessionId: string): Promise<void> {
  await fetch(`${API_BASE}/study/sessions/${sessionId}/end`, { method: "POST" })
}

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
}

function FlashCard({ card, showAnswer }: FlashCardProps) {
  return (
    <div className="relative h-64 w-full max-w-2xl" style={{ perspective: "1000px" }}>
      <motion.div
        className="absolute inset-0"
        animate={{ rotateY: showAnswer ? 180 : 0 }}
        transition={{ duration: 0.4, ease: "easeInOut" }}
        style={{ transformStyle: "preserve-3d" }}
      >
        {/* Front — question */}
        <div
          className="absolute inset-0 flex flex-col items-center justify-center rounded-xl border border-border bg-card p-8 text-center shadow-md"
          style={{ backfaceVisibility: "hidden" }}
        >
          <p className="text-xl font-semibold text-foreground">{card.question}</p>
        </div>

        {/* Back — question + answer (rotated 180 so it reads correctly when flipped) */}
        <div
          className="absolute inset-0 flex flex-col items-center justify-center gap-4 rounded-xl border border-border bg-card p-8 text-center shadow-md"
          style={{ backfaceVisibility: "hidden", transform: "rotateY(180deg)" }}
        >
          <p className="text-sm text-muted-foreground">{card.question}</p>
          <hr className="w-3/4 border-border" />
          <p className="text-lg font-medium text-foreground">{card.answer}</p>
        </div>
      </motion.div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Rating buttons
// ---------------------------------------------------------------------------

const RATINGS: { label: string; value: Rating; className: string }[] = [
  {
    label: "Again",
    value: "again",
    className: "bg-red-100 text-red-700 border-red-200 hover:bg-red-200",
  },
  {
    label: "Hard",
    value: "hard",
    className: "bg-orange-100 text-orange-700 border-orange-200 hover:bg-orange-200",
  },
  {
    label: "Good",
    value: "good",
    className: "bg-green-100 text-green-700 border-green-200 hover:bg-green-200",
  },
  {
    label: "Easy",
    value: "easy",
    className: "bg-blue-100 text-blue-700 border-blue-200 hover:bg-blue-200",
  },
]

// ---------------------------------------------------------------------------
// SessionComplete screen
// ---------------------------------------------------------------------------

interface SessionCompleteProps {
  reviewed: number
  correct: number
  nextReviewDate: string | null
  onBack: () => void
}

function SessionComplete({ reviewed, correct, nextReviewDate, onBack }: SessionCompleteProps) {
  const pct = reviewed === 0 ? 0 : Math.round((correct / reviewed) * 100)

  return (
    <div className="flex flex-col items-center gap-6 text-center">
      <h2 className="text-2xl font-bold text-foreground">Session Complete!</h2>
      <div className="flex gap-8">
        <div className="flex flex-col items-center">
          <span className="text-3xl font-bold text-foreground">{reviewed}</span>
          <span className="text-sm text-muted-foreground">Cards reviewed</span>
        </div>
        <div className="flex flex-col items-center">
          <span className="text-3xl font-bold text-green-600">{pct}%</span>
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
      <button
        onClick={onBack}
        className="rounded bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
      >
        Back to Study
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// StudySession — main component
// ---------------------------------------------------------------------------

interface StudySessionProps {
  documentId: string | null
  onExit: () => void
}

type SessionState = "loading" | "studying" | "complete" | "empty"

export function StudySession({ documentId, onExit }: StudySessionProps) {
  const [sessionState, setSessionState] = useState<SessionState>("loading")
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [queue, setQueue] = useState<Flashcard[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [showAnswer, setShowAnswer] = useState(false)
  const [reviewed, setReviewed] = useState(0)
  const [correct, setCorrect] = useState(0)
  const [isRating, setIsRating] = useState(false)
  // Track next review date as minimum due_date across remaining cards
  const [nextReviewDate, setNextReviewDate] = useState<string | null>(null)

  const total = queue.length

  useEffect(() => {
    let cancelled = false

    async function init() {
      try {
        const [sid, cards] = await Promise.all([
          startSession(documentId),
          fetchDueCards(documentId),
        ])
        if (cancelled) return
        setSessionId(sid)
        setQueue(cards)
        setSessionState(cards.length === 0 ? "empty" : "studying")
      } catch {
        if (!cancelled) setSessionState("empty")
      }
    }

    void init()
    return () => {
      cancelled = true
    }
  }, [documentId])

  async function handleRate(rating: Rating) {
    if (!sessionId || isRating) return
    const card = queue[currentIndex]
    if (!card) return

    setIsRating(true)

    try {
      await submitReview(card.id, rating, sessionId)
      const isCorrect = rating !== "again"
      const newReviewed = reviewed + 1
      const newCorrect = correct + (isCorrect ? 1 : 0)
      setReviewed(newReviewed)
      setCorrect(newCorrect)

      // Track soonest future due_date for "next review" display
      if (card.due_date && (!nextReviewDate || card.due_date < nextReviewDate)) {
        setNextReviewDate(card.due_date)
      }

      const nextIndex = currentIndex + 1
      if (nextIndex >= queue.length) {
        // End session
        await endSession(sessionId)
        setSessionState("complete")
      } else {
        setCurrentIndex(nextIndex)
        setShowAnswer(false)
      }
    } finally {
      setIsRating(false)
    }
  }

  async function handleBackToStudy() {
    if (sessionId && sessionState !== "complete") {
      await endSession(sessionId)
    }
    onExit()
  }

  if (sessionState === "loading") {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 size={32} className="animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (sessionState === "empty") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
        <p className="text-sm text-muted-foreground">No cards due for review right now.</p>
        <button
          onClick={onExit}
          className="rounded border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-accent"
        >
          Back to Study
        </button>
      </div>
    )
  }

  if (sessionState === "complete") {
    return (
      <div className="flex h-full items-center justify-center">
        <SessionComplete
          reviewed={reviewed}
          correct={correct}
          nextReviewDate={nextReviewDate}
          onBack={onExit}
        />
      </div>
    )
  }

  const currentCard = queue[currentIndex]
  if (!currentCard) return null

  return (
    <div className="flex h-full flex-col items-center gap-6 overflow-auto px-6 py-8">
      <ProgressBar done={reviewed} total={total} />

      {/* Card with AnimatePresence for slide-out between cards */}
      <AnimatePresence mode="wait">
        <motion.div
          key={currentCard.id}
          initial={{ x: 300, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: -300, opacity: 0 }}
          transition={{ duration: 0.25, ease: "easeInOut" }}
          className="w-full max-w-2xl"
        >
          <FlashCard card={currentCard} showAnswer={showAnswer} />
        </motion.div>
      </AnimatePresence>

      {/* Show Answer / Rating buttons */}
      {!showAnswer ? (
        <button
          onClick={() => setShowAnswer(true)}
          className="rounded bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Show Answer
        </button>
      ) : (
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
      )}

      {/* Exit button */}
      <button
        onClick={() => void handleBackToStudy()}
        className="text-xs text-muted-foreground hover:text-foreground"
      >
        End session
      </button>
    </div>
  )
}
