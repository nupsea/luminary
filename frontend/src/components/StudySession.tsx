/**
 * StudySession — full-screen flashcard review with Framer Motion flip animation.
 *
 * Props:
 *   documentId   — optional document scope for GET /study/due
 *   onExit       — callback invoked after POST /study/sessions/{id}/end
 */

import { AnimatePresence, motion } from "framer-motion"
import { useEffect, useRef, useState } from "react"
import { Loader2, Check, AlertTriangle, X as XIcon, Mic, MicOff } from "lucide-react"

// ---------------------------------------------------------------------------
// Web Speech API types (not included in all TS lib targets)
// ---------------------------------------------------------------------------
interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList
  resultIndex: number
}
interface SpeechRecognitionResultList {
  readonly length: number
  item(index: number): SpeechRecognitionResult
  [index: number]: SpeechRecognitionResult
}
interface SpeechRecognitionResult {
  readonly isFinal: boolean
  readonly length: number
  item(index: number): SpeechRecognitionAlternative
  [index: number]: SpeechRecognitionAlternative
}
interface SpeechRecognitionAlternative {
  readonly transcript: string
  readonly confidence: number
}
interface SpeechRecognitionConstructor {
  new (): SpeechRecognitionInstance
}
interface SpeechRecognitionInstance extends EventTarget {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((e: SpeechRecognitionEvent) => void) | null
  onend: (() => void) | null
  onerror: ((e: Event) => void) | null
  start(): void
  stop(): void
}

// Detect browser SpeechRecognition support (Chrome/Edge ship webkitSpeechRecognition)
const SpeechRecognitionAPI: SpeechRecognitionConstructor | null =
  (typeof window !== "undefined" &&
    ((window as unknown as { SpeechRecognition?: SpeechRecognitionConstructor }).SpeechRecognition ??
      (window as unknown as { webkitSpeechRecognition?: SpeechRecognitionConstructor }).webkitSpeechRecognition)) ||
  null

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

interface TeachbackResult {
  score: number
  correct_points: string[]
  missing_points: string[]
  misconceptions: string[]
  correction_flashcard_id: string | null
}

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

async function submitTeachback(
  flashcardId: string,
  userExplanation: string,
): Promise<TeachbackResult> {
  const res = await fetch(`${API_BASE}/study/teachback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ flashcard_id: flashcardId, user_explanation: userExplanation }),
  })
  if (!res.ok) throw new Error("Teachback request failed")
  return res.json() as Promise<TeachbackResult>
}

// ---------------------------------------------------------------------------
// TeachbackPanel — textarea + submit + results
// ---------------------------------------------------------------------------

interface TeachbackPanelProps {
  card: Flashcard
  onNext: () => void
}

function TeachbackPanel({ card, onNext }: TeachbackPanelProps) {
  const [explanation, setExplanation] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [result, setResult] = useState<TeachbackResult | null>(null)
  const [isRecording, setIsRecording] = useState(false)
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
  // Tracks whether the current stop was user-initiated (manual) vs natural end.
  // The Web Speech API always fires onend after stop(); without this guard,
  // a manual stop followed by the user typing before onend fires would have
  // onend overwrite those edits with the stale finalTranscript.
  const manualStopRef = useRef(false)

  // Clean up recognition on unmount
  useEffect(() => {
    return () => {
      manualStopRef.current = true
      recognitionRef.current?.stop()
    }
  }, [])

  function toggleRecording() {
    if (isRecording) {
      manualStopRef.current = true
      recognitionRef.current?.stop()
      setIsRecording(false)
      return
    }
    if (!SpeechRecognitionAPI) return
    const recognition = new SpeechRecognitionAPI()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = "en-US"

    manualStopRef.current = false
    let finalTranscript = ""
    recognition.onresult = (e: SpeechRecognitionEvent) => {
      let interim = ""
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const segment = e.results[i][0].transcript
        if (e.results[i].isFinal) {
          finalTranscript += segment
        } else {
          interim += segment
        }
      }
      // Show final + current interim in textarea in real-time
      setExplanation(finalTranscript + interim)
    }

    recognition.onend = () => {
      // On natural end: commit final transcript (drops trailing interim).
      // On manual stop: skip setExplanation so user edits made after clicking
      // stop are not overwritten by the stale finalTranscript closure value.
      if (!manualStopRef.current) {
        setExplanation(finalTranscript)
      }
      setIsRecording(false)
      recognitionRef.current = null
    }

    recognition.onerror = () => {
      setIsRecording(false)
      recognitionRef.current = null
    }

    recognitionRef.current = recognition
    recognition.start()
    setIsRecording(true)
  }

  async function handleSubmit() {
    if (!explanation.trim()) return
    setIsSubmitting(true)
    try {
      const res = await submitTeachback(card.id, explanation)
      setResult(res)
    } finally {
      setIsSubmitting(false)
    }
  }

  function scoreBadgeClass(score: number): string {
    if (score >= 80) return "bg-green-100 text-green-700"
    if (score >= 60) return "bg-amber-100 text-amber-700"
    return "bg-red-100 text-red-700"
  }

  if (result) {
    return (
      <div className="flex w-full max-w-2xl flex-col gap-4">
        <p className="text-base font-medium text-foreground">{card.question}</p>
        <div className="flex items-center gap-2">
          <span className={`rounded-full px-3 py-1 text-sm font-bold ${scoreBadgeClass(result.score)}`}>
            Score: {result.score}/100
          </span>
        </div>

        {result.correct_points.length > 0 && (
          <div className="flex flex-col gap-1">
            <p className="text-xs font-semibold text-green-700">Correct points</p>
            {result.correct_points.map((p, i) => (
              <div key={i} className="flex items-start gap-1.5 text-sm text-foreground">
                <Check size={14} className="mt-0.5 shrink-0 text-green-600" />
                {p}
              </div>
            ))}
          </div>
        )}

        {result.missing_points.length > 0 && (
          <div className="flex flex-col gap-1">
            <p className="text-xs font-semibold text-amber-700">Missing points</p>
            {result.missing_points.map((p, i) => (
              <div key={i} className="flex items-start gap-1.5 text-sm text-foreground">
                <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-500" />
                {p}
              </div>
            ))}
          </div>
        )}

        {result.misconceptions.length > 0 && (
          <div className="flex flex-col gap-1">
            <p className="text-xs font-semibold text-red-700">Misconceptions</p>
            {result.misconceptions.map((p, i) => (
              <div key={i} className="flex items-start gap-1.5 text-sm text-foreground">
                <XIcon size={14} className="mt-0.5 shrink-0 text-red-500" />
                {p}
              </div>
            ))}
          </div>
        )}

        <button
          onClick={onNext}
          className="self-start rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Next card
        </button>
      </div>
    )
  }

  return (
    <div className="flex w-full max-w-2xl flex-col gap-3">
      <p className="text-base font-medium text-foreground">{card.question}</p>
      <p className="text-xs text-muted-foreground">Explain the answer in your own words:</p>
      <div className="relative">
        <textarea
          value={explanation}
          onChange={(e) => setExplanation(e.target.value)}
          placeholder="Type your explanation here..."
          className="h-32 w-full resize-none rounded border border-border bg-background p-3 pr-10 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          autoFocus
        />
        {/* Microphone button — top-right corner of textarea */}
        <button
          type="button"
          onClick={toggleRecording}
          disabled={!SpeechRecognitionAPI}
          title={SpeechRecognitionAPI ? (isRecording ? "Stop recording" : "Start voice input") : "Voice input not supported in this browser"}
          aria-label={SpeechRecognitionAPI ? (isRecording ? "Stop recording" : "Start voice input") : "Voice input not supported in this browser"}
          className="absolute right-2 top-2 rounded p-1 text-muted-foreground transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isRecording ? (
            <MicOff size={16} className="animate-pulse text-destructive" />
          ) : (
            <Mic size={16} />
          )}
        </button>
      </div>
      {isRecording && (
        <p className="text-xs text-destructive">Recording... click the mic again to stop.</p>
      )}
      <button
        onClick={() => void handleSubmit()}
        disabled={isSubmitting || !explanation.trim()}
        className="flex items-center gap-2 self-start rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        {isSubmitting && <Loader2 size={14} className="animate-spin" />}
        Submit
      </button>
    </div>
  )
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
  onFlip?: () => void
}

function FlashCard({ card, showAnswer, onFlip }: FlashCardProps) {
  return (
    <div
      className="relative h-64 w-full max-w-2xl cursor-pointer"
      style={{ perspective: "1000px", position: "relative" }}
      onClick={onFlip}
    >
      {/* Front — question */}
      <motion.div
        className="absolute flex h-full w-full flex-col items-center justify-center rounded-xl border border-border bg-card p-8 text-center shadow-md"
        animate={{ rotateY: showAnswer ? -180 : 0 }}
        transition={{ duration: 0.4, ease: "easeInOut" }}
        style={{ backfaceVisibility: "hidden" }}
      >
        <p className="text-xl font-semibold text-foreground">{card.question}</p>
      </motion.div>

      {/* Back — question + answer */}
      <motion.div
        className="absolute flex h-full w-full flex-col items-center justify-center gap-4 rounded-xl border border-border bg-card p-8 text-center shadow-md"
        initial={{ rotateY: 180 }}
        animate={{ rotateY: showAnswer ? 0 : 180 }}
        transition={{ duration: 0.4, ease: "easeInOut" }}
        style={{ backfaceVisibility: "hidden" }}
      >
        <p className="text-sm text-muted-foreground">{card.question}</p>
        <hr className="w-3/4 border-border" />
        <p className="text-lg font-medium text-foreground">{card.answer}</p>
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
  const [teachbackMode, setTeachbackMode] = useState(false)
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

  function handleTeachbackNext() {
    const nextIndex = currentIndex + 1
    setReviewed(reviewed + 1)
    if (nextIndex >= queue.length) {
      void (async () => {
        if (sessionId) await endSession(sessionId)
        setSessionState("complete")
      })()
    } else {
      setCurrentIndex(nextIndex)
      setShowAnswer(false)
      setTeachbackMode(false)
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

      {/* Mode toggle */}
      <div className="flex rounded-md border border-border text-sm">
        <button
          onClick={() => { setTeachbackMode(false); setShowAnswer(false) }}
          className={`rounded-l-md px-4 py-1.5 transition-colors ${!teachbackMode ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"}`}
        >
          Flashcard
        </button>
        <button
          onClick={() => setTeachbackMode(true)}
          className={`rounded-r-md px-4 py-1.5 transition-colors ${teachbackMode ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"}`}
        >
          Teach-back
        </button>
      </div>

      {teachbackMode ? (
        <TeachbackPanel card={currentCard} onNext={handleTeachbackNext} />
      ) : (
        <>
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
              <FlashCard
                card={currentCard}
                showAnswer={showAnswer}
                onFlip={() => setShowAnswer((prev) => !prev)}
              />
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
        </>
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
