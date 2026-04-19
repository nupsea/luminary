/**
 * StudySession — full-screen flashcard review with Framer Motion flip animation.
 *
 * Props:
 *   documentId   — optional document scope for GET /study/due
 *   onExit       — callback invoked after POST /study/sessions/{id}/end
 */

import { AnimatePresence, motion } from "framer-motion"
import { useEffect, useRef, useState } from "react"
import { ChevronDown, ChevronUp, ExternalLink, Loader2, Check, AlertTriangle, X as XIcon, Mic, MicOff } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { ClozeCard } from "@/components/ClozeCard"

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

import { API_BASE } from "@/lib/config"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Flashcard {
  id: string
  question: string
  answer: string
  source_excerpt: string
  due_date: string | null
  // S138: section_id populated by /study/due join with ChunkModel
  section_id: string | null
  // S154: cloze deletion fields
  flashcard_type: string | null
  cloze_text: string | null
}

// ---------------------------------------------------------------------------
// S155: SourceContextPanel types
// ---------------------------------------------------------------------------

interface SourceContext {
  section_heading: string
  section_preview: string
  document_title: string
  pdf_page_number: number | null
  section_id: string
  document_id: string
}

async function fetchSourceContext(cardId: string): Promise<SourceContext | null> {
  try {
    const res = await fetch(`${API_BASE}/flashcards/${encodeURIComponent(cardId)}/source-context`)
    if (!res.ok) return null
    return res.json() as Promise<SourceContext>
  } catch {
    return null
  }
}

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
            {/* Opens in new tab so the study session is not interrupted */}
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
// S138: SourcePanel types
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

interface SourcePanelProps {
  card: Flashcard
}

function SourcePanel({ card }: SourcePanelProps) {
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
          {/* Source excerpt */}
          {card.source_excerpt && (
            <blockquote className="border-l-2 border-border pl-3 text-xs text-muted-foreground italic">
              {card.source_excerpt}
            </blockquote>
          )}

          {/* Web references */}
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
            <p className="text-xs text-muted-foreground">
              No web references for this section yet.
            </p>
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

async function fetchDueCards(
  documentId: string | null,
  collectionId: string | null = null,
  filters: any = {}
): Promise<Flashcard[]> {
  const params = new URLSearchParams({ limit: "50" })
  if (documentId) params.set("document_id", documentId)
  if (collectionId) params.set("collection_id", collectionId)
  if (filters.tag) params.set("tag", filters.tag)
  if (filters.document_ids?.length) {
    filters.document_ids.forEach((id: string) => params.append("document_ids", id))
  }
  if (filters.note_ids?.length) {
    filters.note_ids.forEach((id: string) => params.append("note_ids", id))
  }
  
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
      className="relative min-h-64 w-full max-w-2xl cursor-pointer"
      style={{ perspective: "1000px", position: "relative" }}
      onClick={onFlip}
    >
      {/* Front — question (MarkdownRenderer for syntax highlighting in code blocks) */}
      <motion.div
        className="absolute flex min-h-64 w-full flex-col items-center justify-center overflow-auto rounded-xl border border-border bg-card p-8 text-center shadow-md"
        animate={{ rotateY: showAnswer ? -180 : 0 }}
        transition={{ duration: 0.4, ease: "easeInOut" }}
        style={{ backfaceVisibility: "hidden" }}
      >
        <MarkdownRenderer className="text-xl font-semibold text-foreground">{card.question}</MarkdownRenderer>
      </motion.div>

      {/* Back — question + answer (MarkdownRenderer for syntax highlighting in code blocks) */}
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
  documentId?: string | null
  collectionId?: string | null
  filters?: {
    tag?: string
    document_ids?: string[]
    note_ids?: string[]
  }
  onExit: () => void
}

type SessionState = "loading" | "studying" | "complete" | "empty"

export function StudySession({ documentId, collectionId, filters, onExit }: StudySessionProps) {
  const [sessionState, setSessionState] = useState<SessionState>("loading")
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [queue, setQueue] = useState<Flashcard[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [showAnswer, setShowAnswer] = useState(false)
  const [reviewed, setReviewed] = useState(0)
  const [correct, setCorrect] = useState(0)
  const [isRating, setIsRating] = useState(false)
  const [teachbackMode, setTeachbackMode] = useState(false)
  // S138: track last rating to show SourcePanel on "again"
  const [lastRating, setLastRating] = useState<Rating | null>(null)
  // Track next review date as minimum due_date across remaining cards
  const [nextReviewDate, setNextReviewDate] = useState<string | null>(null)
  // S155: source context panel state
  const [sourceContext, setSourceContext] = useState<SourceContext | null>(null)
  const [sourceContextLoading, setSourceContextLoading] = useState(false)
  const dismissedSourceContextIds = useRef(new Set<string>())

  const total = queue.length

  useEffect(() => {
    let cancelled = false

    async function init() {
      try {
        const [sid, cards] = await Promise.all([
          startSession(documentId ?? null), // startSession still just needs a docId if it's doc-focused, or null for general
          fetchDueCards(documentId || null, collectionId || null, filters || {}),
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
  }, [documentId, collectionId, filters])

  async function handleRate(rating: Rating) {
    if (!sessionId || isRating) return
    const card = queue[currentIndex]
    if (!card) return

    setIsRating(true)

    try {
      // AC6: submit rating immediately -- do not wait for source context fetch
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

      setLastRating(rating)

      // S155: lazy-fetch source context after "again" or "hard" (AC7)
      if (rating === "again" || rating === "hard") {
        if (!dismissedSourceContextIds.current.has(card.id)) {
          setSourceContextLoading(true)
          const ctx = await fetchSourceContext(card.id)
          setSourceContextLoading(false)
          if (ctx !== null) {
            setSourceContext(ctx)
            // Panel shown -- do not advance; user clicks Continue (which calls advanceCard)
            return
          }
        }
        // 404, error, or dismissed: fall through to advance for "hard";
        // for "again" stay and show S138 SourcePanel (advanceCard driven by Continue)
        if (rating === "hard") {
          const nextIndex = currentIndex + 1
          if (nextIndex >= queue.length) {
            await endSession(sessionId)
            setSessionState("complete")
          } else {
            setCurrentIndex(nextIndex)
            setShowAnswer(false)
            setLastRating(null)
          }
        }
        // "again" with no source context: stays on card showing S138 SourcePanel
        return
      }

      // "good" / "easy": advance immediately
      const nextIndex = currentIndex + 1
      if (nextIndex >= queue.length) {
        await endSession(sessionId)
        setSessionState("complete")
      } else {
        setCurrentIndex(nextIndex)
        setShowAnswer(false)
        setLastRating(null)
      }
    } finally {
      setIsRating(false)
    }
  }

  async function advanceCard() {
    // Called by the "Continue" button after viewing SourceContextPanel (S155) or SourcePanel (S138).
    setSourceContext(null)
    setSourceContextLoading(false)
    const nextIndex = currentIndex + 1
    if (nextIndex >= queue.length) {
      if (sessionId) await endSession(sessionId)
      setSessionState("complete")
    } else {
      setCurrentIndex(nextIndex)
      setShowAnswer(false)
      setLastRating(null)
    }
  }

  function handleDismissSourceContext() {
    const card = queue[currentIndex]
    if (card) dismissedSourceContextIds.current.add(card.id)
    // advanceCard() clears sourceContext; no need to call setSourceContext(null) here
    void advanceCard()
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
          {/* S154: dispatch to ClozeCard for cloze flashcard_type with valid blanks */}
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
                <ClozeCard
                  card={currentCard}
                  onRate={handleRate}
                  isRating={isRating}
                />
              </motion.div>
            </AnimatePresence>
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

              {/* Show Answer / Rating buttons -- hidden once a rating is recorded (lastRating set) */}
              {!showAnswer ? (
                <button
                  onClick={() => setShowAnswer(true)}
                  className="rounded bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
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

              {/* S155: Source context panel -- shown after "again" or "hard" when source context fetched */}
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
                  />
                  <button
                    onClick={() => void advanceCard()}
                    className="rounded bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                  >
                    Continue
                  </button>
                </>
              )}

              {/* S138: Source panel -- shown after "again" only when no S155 context available */}
              {lastRating === "again" && sourceContext === null && !sourceContextLoading && (
                <>
                  <SourcePanel card={currentCard} />
                  <button
                    onClick={() => void advanceCard()}
                    className="rounded bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                  >
                    Continue
                  </button>
                </>
              )}
            </>
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
