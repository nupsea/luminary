/**
 * TeachbackSession -- dedicated teach-back study experience.
 *
 * Separated from FlashcardSession to provide:
 *  - Persistent sessions that survive tab switches
 *  - Resume incomplete sessions
 *  - Rich feedback per card with retry
 *  - Session summary with all results
 *
 * Props:
 *   documentId   -- optional document scope for card fetching
 *   collectionId -- optional collection scope
 *   filters      -- optional tag/document_ids/note_ids filters
 *   resumeSessionId -- when set, resume an existing incomplete session
 *   onExit       -- callback when leaving the session
 */

import { AnimatePresence, motion } from "framer-motion"
import { useEffect, useRef, useState } from "react"
import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronUp,
  Loader2,
  Mic,
  MicOff,
  X as XIcon,
  BookOpen,
  MessageSquare,
} from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { useAppStore } from "@/store"
import {
  type Flashcard,
  type PendingTeachback,
  type TeachbackResultItem,
  startSession,
  fetchDueCards,
  endSession,
  submitTeachbackAsync,
  fetchTeachbackResults,
  fetchSessionTeachbackResults,
  scoreBadgeClass,
} from "@/lib/studyApi"

// ---------------------------------------------------------------------------
// Web Speech API types
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

const SpeechRecognitionAPI: SpeechRecognitionConstructor | null =
  (typeof window !== "undefined" &&
    ((window as unknown as { SpeechRecognition?: SpeechRecognitionConstructor }).SpeechRecognition ??
      (window as unknown as { webkitSpeechRecognition?: SpeechRecognitionConstructor }).webkitSpeechRecognition)) ||
  null

// ---------------------------------------------------------------------------
// Progress bar
// ---------------------------------------------------------------------------

function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total === 0 ? 0 : Math.round((done / total) * 100)
  return (
    <div className="w-full max-w-2xl">
      <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {done} of {total} explained
        </span>
        <span>{pct}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
        <div
          className="h-full rounded-full bg-violet-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Inline feedback for a single teach-back result
// ---------------------------------------------------------------------------

function InlineTeachbackFeedback({ result }: { result: TeachbackResultItem }) {
  const score = result.score ?? 0
  const passed = score >= 60
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        <span className={`rounded-full px-3 py-0.5 text-xs font-bold ${scoreBadgeClass(score)}`}>
          {score}/100
        </span>
        <span className={`text-sm font-medium ${passed ? "text-green-700 dark:text-green-400" : "text-amber-700 dark:text-amber-400"}`}>
          {passed ? "Good explanation!" : "Needs improvement"}
        </span>
      </div>

      {result.correct_points.length > 0 && (
        <div className="flex flex-col gap-0.5">
          <p className="text-xs font-semibold text-green-700 dark:text-green-400">Correct</p>
          {result.correct_points.map((p, i) => (
            <div key={i} className="flex items-start gap-1.5 text-xs text-foreground">
              <Check size={12} className="mt-0.5 shrink-0 text-green-600" />
              {p}
            </div>
          ))}
        </div>
      )}

      {result.missing_points.length > 0 && (
        <div className="flex flex-col gap-0.5">
          <p className="text-xs font-semibold text-amber-700 dark:text-amber-400">Missing</p>
          {result.missing_points.map((p, i) => (
            <div key={i} className="flex items-start gap-1.5 text-xs text-foreground">
              <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber-500" />
              {p}
            </div>
          ))}
        </div>
      )}

      {result.misconceptions.length > 0 && (
        <div className="flex flex-col gap-0.5">
          <p className="text-xs font-semibold text-red-700 dark:text-red-400">Misconceptions</p>
          {result.misconceptions.map((p, i) => (
            <div key={i} className="flex items-start gap-1.5 text-xs text-foreground">
              <XIcon size={12} className="mt-0.5 shrink-0 text-red-500" />
              {p}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// TeachbackPanel -- textarea + submit + inline feedback + retry
// ---------------------------------------------------------------------------

interface TeachbackPanelProps {
  card: Flashcard
  onNext: () => void
  onSubmitAsync: (cardId: string, question: string, explanation: string) => void
  currentResult: TeachbackResultItem | null
  isEvaluating: boolean
  previousAttempt: TeachbackResultItem | null
}

function TeachbackPanel({
  card,
  onNext,
  onSubmitAsync,
  currentResult,
  isEvaluating,
  previousAttempt,
}: TeachbackPanelProps) {
  const [explanation, setExplanation] = useState("")
  const [submitted, setSubmitted] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
  const manualStopRef = useRef(false)

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
      setExplanation(finalTranscript + interim)
    }

    recognition.onend = () => {
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

  function handleSubmit() {
    if (!explanation.trim()) return
    onSubmitAsync(card.id, card.question, explanation.trim())
    setSubmitted(true)
  }

  function handleRetry() {
    setExplanation("")
    setSubmitted(false)
  }

  const showForm = !submitted
  const showEvaluating = submitted && !currentResult && isEvaluating
  const evalErrored = submitted && currentResult != null && currentResult.status === "error"
  const showResult = submitted && currentResult != null && currentResult.status === "complete"
  const showError = evalErrored || (submitted && !isEvaluating && !currentResult)
  const failed = showResult && (currentResult.score ?? 0) < 60

  return (
    <div className="flex w-full max-w-2xl flex-col gap-4">
      {/* Previous attempt banner -- shown when card was re-queued */}
      {previousAttempt && !submitted && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-950/30">
          <p className="mb-2 text-xs font-semibold text-amber-800 dark:text-amber-300">
            Previous attempt -- score {previousAttempt.score}/100
          </p>
          <InlineTeachbackFeedback result={previousAttempt} />
          <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
            Try explaining again with the feedback above in mind.
          </p>
        </div>
      )}

      {/* Card question in a distinct card */}
      <div className="rounded-xl border border-violet-200 bg-violet-50/50 p-5 dark:border-violet-800 dark:bg-violet-950/20">
        <div className="mb-2 flex items-center gap-2">
          <BookOpen size={14} className="text-violet-500" />
          <span className="text-xs font-semibold uppercase tracking-wider text-violet-600 dark:text-violet-400">
            Explain this concept
          </span>
        </div>
        <MarkdownRenderer className="text-base font-medium text-foreground">
          {card.question}
        </MarkdownRenderer>
      </div>

      {/* Input form */}
      {showForm && (
        <div className="flex flex-col gap-3">
          <p className="text-xs text-muted-foreground">
            Explain the answer in your own words -- as if teaching someone else:
          </p>
          <div className="relative">
            <textarea
              value={explanation}
              onChange={(e) => setExplanation(e.target.value)}
              placeholder="Type your explanation here..."
              className="h-36 w-full resize-none rounded-lg border border-border bg-background p-4 pr-10 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-violet-400"
              autoFocus
            />
            <button
              type="button"
              onClick={toggleRecording}
              disabled={!SpeechRecognitionAPI}
              title={
                SpeechRecognitionAPI
                  ? isRecording
                    ? "Stop recording"
                    : "Start voice input"
                  : "Voice input not supported in this browser"
              }
              className="absolute right-3 top-3 rounded p-1 text-muted-foreground transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
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
            onClick={handleSubmit}
            disabled={!explanation.trim()}
            className="self-start rounded-lg bg-violet-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
          >
            Submit Explanation
          </button>
        </div>
      )}

      {/* Evaluating spinner */}
      {showEvaluating && (
        <div className="flex flex-col gap-3 rounded-lg border border-border bg-muted/30 p-4">
          <div className="flex items-center gap-2">
            <Loader2 size={16} className="animate-spin text-violet-500" />
            <span className="text-sm text-muted-foreground">Evaluating your explanation...</span>
          </div>
          <button
            onClick={onNext}
            className="self-start text-xs text-muted-foreground underline hover:text-foreground"
          >
            Skip to next card (results will appear in session summary)
          </button>
        </div>
      )}

      {/* Evaluation error */}
      {showError && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-lg border-2 border-red-300 bg-red-50 p-4 dark:border-red-700 dark:bg-red-950/40"
        >
          <p className="mb-3 text-center text-sm font-semibold text-red-800 dark:text-red-300">
            Evaluation failed. Your answer was recorded -- you can continue.
          </p>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={onNext}
              autoFocus
              className="flex items-center gap-2 rounded-lg bg-red-600 px-6 py-2.5 text-sm font-bold text-white hover:bg-red-700"
            >
              Next Card <ArrowRight size={18} />
            </button>
            <button
              onClick={handleRetry}
              className="rounded-lg border-2 border-red-300 px-5 py-2.5 text-sm font-semibold text-red-800 hover:bg-red-100 dark:border-red-700 dark:text-red-300"
            >
              Try Again
            </button>
          </div>
        </motion.div>
      )}

      {/* Inline result feedback + action banner */}
      {showResult && (
        <>
          <div className="rounded-lg border border-border bg-card p-4">
            <InlineTeachbackFeedback result={currentResult} />
          </div>

          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
            className={`rounded-lg p-4 ${
              failed
                ? "border-2 border-amber-400 bg-amber-50 dark:border-amber-600 dark:bg-amber-950/40"
                : "border-2 border-green-400 bg-green-50 dark:border-green-600 dark:bg-green-950/40"
            }`}
          >
            <p
              className={`mb-3 text-center text-sm font-semibold ${
                failed
                  ? "text-amber-800 dark:text-amber-300"
                  : "text-green-800 dark:text-green-300"
              }`}
            >
              {failed
                ? "Review the feedback and try again, or continue."
                : "Great job! Move on to the next card."}
            </p>
            <div className="flex items-center justify-center gap-3">
              <motion.button
                onClick={onNext}
                autoFocus
                initial={{ scale: 0.95 }}
                animate={{ scale: 1 }}
                className={`flex items-center gap-2 rounded-lg px-8 py-3 text-base font-bold shadow-lg ${
                  failed
                    ? "bg-amber-600 text-white hover:bg-amber-700"
                    : "bg-green-600 text-white hover:bg-green-700"
                }`}
              >
                Next Card <ArrowRight size={20} />
              </motion.button>
              {failed && (
                <button
                  onClick={handleRetry}
                  className="rounded-lg border-2 border-amber-400 px-6 py-3 text-sm font-semibold text-amber-800 hover:bg-amber-100 dark:border-amber-600 dark:text-amber-300"
                >
                  Try Again
                </button>
              )}
            </div>
          </motion.div>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// TeachbackResultsPanel -- session summary
// ---------------------------------------------------------------------------

interface TeachbackStats {
  allDone: boolean
  completedCount: number
  avgScore: number
  passCount: number
}

function useTeachbackPolling(pending: PendingTeachback[]): {
  results: TeachbackResultItem[] | undefined
  stats: TeachbackStats
} {
  const realIds = pending
    .map((t) => t.id)
    .filter((id) => !id.startsWith("temp-") && !id.startsWith("error-"))
  const hasUnresolved = pending.some(
    (t) => t.id.startsWith("temp-") || t.id.startsWith("error-"),
  )
  const { data: results } = useQuery({
    queryKey: ["teachback-results", ...realIds],
    queryFn: () => fetchTeachbackResults(realIds),
    refetchInterval: (query) => {
      if (hasUnresolved) return 2000
      const items = query.state.data
      if (!items) return 2000
      return items.every((r) => r.status !== "pending") ? false : 2000
    },
    enabled: realIds.length > 0 || hasUnresolved,
    refetchOnMount: "always",
  })

  const completed = results?.filter((r) => r.status === "complete") ?? []
  const allDone =
    !hasUnresolved &&
    results != null &&
    results.length === realIds.length &&
    results.every((r) => r.status !== "pending")
  const avgScore =
    completed.length > 0
      ? Math.round(completed.reduce((s, r) => s + (r.score ?? 0), 0) / completed.length)
      : 0
  const passCount = completed.filter((r) => (r.score ?? 0) >= 60).length

  return {
    results,
    stats: { allDone, completedCount: completed.length, avgScore, passCount },
  }
}

function TeachbackResultsPanel({
  pending,
  stats,
  results,
}: {
  pending: PendingTeachback[]
  stats: TeachbackStats
  results: TeachbackResultItem[] | undefined
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  return (
    <div className="flex w-full max-w-2xl flex-col gap-4">
      {/* Summary bar */}
      {stats.allDone && stats.completedCount > 0 && (
        <div className="rounded-lg border border-border bg-card/50 p-4 text-center">
          <span className="text-sm text-muted-foreground">Average score: </span>
          <span
            className={`text-2xl font-bold ${
              stats.avgScore >= 80
                ? "text-green-600"
                : stats.avgScore >= 60
                  ? "text-amber-600"
                  : "text-red-600"
            }`}
          >
            {stats.avgScore}/100
          </span>
          <span className="ml-3 text-sm text-muted-foreground">
            ({stats.passCount}/{stats.completedCount} passed)
          </span>
        </div>
      )}

      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-foreground">Results</h3>
        {!stats.allDone && (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 size={12} className="animate-spin" />
            Evaluating...
          </span>
        )}
      </div>

      {pending.map((tb) => {
        if (tb.id.startsWith("error-")) {
          return (
            <div key={tb.id} className="rounded-lg border border-border bg-muted/30 p-4">
              <p className="text-sm font-medium text-foreground">{tb.question}</p>
              <p className="mt-2 text-xs text-amber-700">
                Submission failed. Check if Ollama is running.
              </p>
            </div>
          )
        }

        if (tb.id.startsWith("temp-")) {
          return (
            <div key={tb.id} className="rounded-lg border border-border bg-muted/30 p-4">
              <p className="text-sm font-medium text-foreground">{tb.question}</p>
              <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 size={12} className="animate-spin" />
                Submitting...
              </div>
            </div>
          )
        }

        const result = results?.find((r) => r.id === tb.id)

        if (!result || result.status === "pending") {
          return (
            <div key={tb.id} className="rounded-lg border border-border bg-muted/30 p-4">
              <p className="text-sm font-medium text-foreground">{tb.question}</p>
              <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 size={12} className="animate-spin" />
                Evaluating...
              </div>
            </div>
          )
        }

        if (result.status === "error") {
          return (
            <div key={tb.id} className="rounded-lg border border-border bg-muted/30 p-4">
              <p className="text-sm font-medium text-foreground">{tb.question}</p>
              <p className="mt-2 text-xs text-amber-700">Evaluation failed.</p>
            </div>
          )
        }

        const isExpanded = expandedId === tb.id
        return (
          <div
            key={tb.id}
            className="rounded-lg border border-border bg-card p-4 cursor-pointer transition-colors hover:bg-accent/30"
            onClick={() => setExpandedId(isExpanded ? null : tb.id)}
          >
            <div className="flex items-center justify-between">
              <p className="flex-1 text-sm font-medium text-foreground">
                {result.question || tb.question}
              </p>
              <div className="flex items-center gap-2">
                <span
                  className={`rounded-full px-3 py-0.5 text-xs font-bold ${scoreBadgeClass(result.score ?? 0)}`}
                >
                  {result.score}/100
                </span>
                {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </div>
            </div>

            {isExpanded && (
              <div className="mt-3 border-t border-border pt-3">
                {result.user_explanation && (
                  <div className="mb-3">
                    <p className="text-xs font-medium text-muted-foreground">Your explanation:</p>
                    <blockquote className="mt-1 border-l-2 border-border pl-3 text-xs text-foreground/80 italic">
                      {result.user_explanation}
                    </blockquote>
                  </div>
                )}
                <InlineTeachbackFeedback result={result} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// SessionComplete screen
// ---------------------------------------------------------------------------

interface SessionCompleteProps {
  reviewed: number
  onBack: () => void
  onStartNext: () => void
  pendingTeachbacks: PendingTeachback[]
}

function SessionComplete({
  reviewed,
  onBack,
  onStartNext,
  pendingTeachbacks,
}: SessionCompleteProps) {
  const { results, stats } = useTeachbackPolling(pendingTeachbacks)

  const displayReviewed = stats.completedCount || reviewed

  return (
    <div className="flex flex-col items-center gap-6 px-4 py-6">
      {stats.allDone ? (
        <div className="flex flex-col items-center gap-2">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-violet-100 dark:bg-violet-900/30">
            <MessageSquare size={28} className="text-violet-600 dark:text-violet-400" />
          </div>
          <h2 className="text-2xl font-bold text-foreground">Session Complete</h2>
        </div>
      ) : (
        <h2 className="text-2xl font-bold text-foreground">Evaluating Your Answers...</h2>
      )}

      {stats.completedCount > 0 && (
        <div className="flex gap-8 text-center">
          <div className="flex flex-col items-center">
            <span className="text-3xl font-bold text-foreground">{displayReviewed}</span>
            <span className="text-sm text-muted-foreground">Cards explained</span>
          </div>
          <div className="flex flex-col items-center">
            <span
              className={`text-3xl font-bold ${
                stats.avgScore >= 80
                  ? "text-green-600"
                  : stats.avgScore >= 60
                    ? "text-amber-600"
                    : "text-red-600"
              }`}
            >
              {stats.avgScore}/100
            </span>
            <span className="text-sm text-muted-foreground">Average Score</span>
          </div>
          <div className="flex flex-col items-center">
            <span className="text-xl font-semibold text-muted-foreground">
              {stats.passCount}/{stats.completedCount}
            </span>
            <span className="text-sm text-muted-foreground">Passed</span>
          </div>
        </div>
      )}

      <TeachbackResultsPanel pending={pendingTeachbacks} stats={stats} results={results} />

      <div className="flex items-center gap-3">
        {stats.allDone && (
          <button
            onClick={onStartNext}
            className="rounded-lg bg-violet-600 px-6 py-2 text-sm font-medium text-white hover:bg-violet-700"
          >
            Start New Session
          </button>
        )}
        <button
          onClick={onBack}
          className={`rounded-lg px-6 py-2 text-sm font-medium ${
            stats.allDone
              ? "border border-border text-muted-foreground hover:bg-accent"
              : "bg-violet-600 text-white hover:bg-violet-700"
          }`}
        >
          Back to Study
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TeachbackSession -- main component
// ---------------------------------------------------------------------------

interface TeachbackSessionProps {
  documentId?: string | null
  collectionId?: string | null
  filters?: {
    tag?: string
    document_ids?: string[]
    note_ids?: string[]
  }
  onExit: () => void
  resumeSessionId?: string | null
}

type SessionState = "loading" | "studying" | "complete" | "empty"

export function TeachbackSession({
  documentId,
  collectionId,
  filters,
  onExit,
  resumeSessionId,
}: TeachbackSessionProps) {
  const [sessionState, setSessionState] = useState<SessionState>("loading")
  const [sessionId, setSessionId] = useState<string | null>(resumeSessionId ?? null)
  const [queue, setQueue] = useState<Flashcard[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [reviewed, setReviewed] = useState(0)
  const [pendingTeachbacks, setPendingTeachbacks] = useState<PendingTeachback[]>([])
  const { setStudySessionId } = useAppStore()

  const initialTotalRef = useRef<number>(0)
  const total = initialTotalRef.current

  // Resume mode: load previous results + remaining cards
  useEffect(() => {
    if (!resumeSessionId) return
    let cancelled = false

    async function resumeInit() {
      try {
        const [prevResults, cards] = await Promise.all([
          fetchSessionTeachbackResults(resumeSessionId!),
          fetchDueCards(documentId || null, collectionId || null, filters || {}),
        ])
        if (cancelled) return

        const previousTeachbacks = prevResults.map((r) => ({
          id: r.id,
          flashcardId: r.flashcard_id,
          question: r.question,
        }))
        setPendingTeachbacks(previousTeachbacks)
        setReviewed(prevResults.length)

        const answeredCardIds = new Set(prevResults.map((r) => r.flashcard_id))
        const remainingCards = cards.filter((c) => !answeredCardIds.has(c.id))

        initialTotalRef.current = prevResults.length + remainingCards.length

        if (remainingCards.length > 0) {
          setQueue(remainingCards)
          setSessionState("studying")
        } else {
          setSessionState("complete")
        }
      } catch {
        if (!cancelled) setSessionState("complete")
      }
    }

    void resumeInit()
    return () => {
      cancelled = true
    }
  }, [resumeSessionId, documentId, collectionId, filters])

  // Normal init (non-resume)
  useEffect(() => {
    if (resumeSessionId) return
    let cancelled = false

    async function init() {
      try {
        const [sid, cards] = await Promise.all([
          startSession(documentId ?? null, "teachback", collectionId ?? null),
          fetchDueCards(documentId || null, collectionId || null, filters || {}),
        ])
        if (cancelled) return
        setSessionId(sid)
        setStudySessionId(sid)
        setQueue(cards)
        initialTotalRef.current = cards.length
        setSessionState(cards.length === 0 ? "empty" : "studying")
      } catch {
        if (!cancelled) setSessionState("empty")
      }
    }

    void init()
    return () => {
      cancelled = true
    }
  }, [documentId, collectionId, filters, resumeSessionId, setStudySessionId])

  // Poll for live results during active session
  const realTeachbackIds = pendingTeachbacks
    .map((t) => t.id)
    .filter((id) => !id.startsWith("temp-") && !id.startsWith("error-"))
  const { data: liveResults } = useQuery({
    queryKey: ["teachback-live-poll", ...realTeachbackIds],
    queryFn: () => fetchTeachbackResults(realTeachbackIds),
    refetchInterval: (query) => {
      if (sessionState !== "studying") return false
      const items = query.state.data
      if (!items) return 2000
      return items.some((r) => r.status === "pending") ? 2000 : false
    },
    enabled: sessionState === "studying" && realTeachbackIds.length > 0,
  })

  function handleTeachbackSubmit(cardId: string, question: string, explanation: string) {
    const tempId = `temp-${Date.now()}-${cardId}`
    setPendingTeachbacks((prev) => [...prev, { id: tempId, flashcardId: cardId, question }])
    void submitTeachbackAsync(cardId, explanation, sessionId)
      .then(({ id }) => {
        setPendingTeachbacks((prev) => prev.map((t) => (t.id === tempId ? { ...t, id } : t)))
      })
      .catch((err) => {
        console.warn("Teachback async submit failed", err)
        setPendingTeachbacks((prev) =>
          prev.map((t) => (t.id === tempId ? { ...t, id: `error-${tempId}` } : t)),
        )
      })
  }

  function handleTeachbackNext() {
    const nextIndex = currentIndex + 1
    setReviewed((r) => r + 1)
    if (nextIndex >= queue.length) {
      void (async () => {
        if (sessionId) await endSession(sessionId)
        setSessionState("complete")
      })()
    } else {
      setCurrentIndex(nextIndex)
    }
  }

  async function handleBackToStudy() {
    if (sessionId && sessionState !== "complete") {
      await endSession(sessionId)
    }
    if (pendingTeachbacks.length > 0 && sessionState !== "complete") {
      setSessionState("complete")
    } else {
      setStudySessionId(null)
      onExit()
    }
  }

  if (sessionState === "loading") {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 size={32} className="animate-spin text-violet-500" />
      </div>
    )
  }

  if (sessionState === "empty") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
        <MessageSquare size={40} className="text-muted-foreground/40" />
        <p className="text-sm text-muted-foreground">No cards due for teach-back right now.</p>
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
          onBack={() => {
            setStudySessionId(null)
            onExit()
          }}
          onStartNext={() => {
            setQueue([])
            setCurrentIndex(0)
            setReviewed(0)
            setPendingTeachbacks([])
            initialTotalRef.current = 0
            setSessionState("loading")
            void (async () => {
              try {
                const [sid, cards] = await Promise.all([
                  startSession(documentId ?? null, "teachback", collectionId ?? null),
                  fetchDueCards(documentId || null, collectionId || null, filters || {}),
                ])
                setSessionId(sid)
                setStudySessionId(sid)
                setQueue(cards)
                initialTotalRef.current = cards.length
                setSessionState(cards.length === 0 ? "empty" : "studying")
              } catch {
                setSessionState("empty")
              }
            })()
          }}
          pendingTeachbacks={pendingTeachbacks}
        />
      </div>
    )
  }

  const currentCard = queue[currentIndex]
  if (!currentCard) return null

  // Derive teach-back evaluation state for current card
  const currentCardTeachbacks = pendingTeachbacks.filter((t) => t.flashcardId === currentCard.id)
  const latestTeachbackEntry = currentCardTeachbacks[currentCardTeachbacks.length - 1] ?? null
  const latestTeachbackId = latestTeachbackEntry?.id ?? null
  const isLatestTemp = latestTeachbackId?.startsWith("temp-") ?? false
  const isLatestError = latestTeachbackId?.startsWith("error-") ?? false
  const currentLiveResult =
    latestTeachbackId && !isLatestTemp && !isLatestError
      ? (liveResults?.find((r) => r.id === latestTeachbackId && r.status !== "pending") ?? null)
      : null
  const isTeachbackEvaluating = latestTeachbackEntry != null && currentLiveResult == null && !isLatestError
  const previousAttemptResult =
    liveResults
      ?.filter(
        (r) =>
          r.flashcard_id === currentCard.id &&
          r.status === "complete" &&
          r.id !== latestTeachbackId,
      )
      .slice(-1)[0] ?? null

  return (
    <div className="flex h-full flex-col items-center gap-6 overflow-auto bg-background px-6 py-8">
      {/* Header */}
      <div className="flex w-full max-w-2xl items-center justify-between">
        <div className="flex items-center gap-2">
          <MessageSquare size={18} className="text-violet-500" />
          <span className="text-sm font-semibold text-violet-600 dark:text-violet-400">
            Teach-back Session
          </span>
        </div>
        <span className="rounded-full bg-violet-100 px-3 py-0.5 text-xs font-medium text-violet-700 dark:bg-violet-900/30 dark:text-violet-400">
          Card {currentIndex + 1} of {queue.length}
        </span>
      </div>

      <ProgressBar done={reviewed} total={total} />

      <AnimatePresence mode="wait">
        <motion.div
          key={`${currentCard.id}-${currentIndex}`}
          initial={{ x: 200, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: -200, opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeInOut" }}
          className="w-full max-w-2xl"
        >
          <TeachbackPanel
            card={currentCard}
            onNext={handleTeachbackNext}
            onSubmitAsync={handleTeachbackSubmit}
            currentResult={currentLiveResult}
            isEvaluating={isTeachbackEvaluating}
            previousAttempt={previousAttemptResult}
          />
        </motion.div>
      </AnimatePresence>

      <button
        onClick={() => void handleBackToStudy()}
        className="text-xs text-muted-foreground hover:text-foreground"
      >
        End session
      </button>
    </div>
  )
}
