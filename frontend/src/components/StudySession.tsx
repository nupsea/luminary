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
import { useAppStore } from "@/store"

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

// ---------------------------------------------------------------------------
// Async teach-back API (non-blocking evaluation)
// ---------------------------------------------------------------------------

interface PendingTeachback {
  id: string           // teachback_result_id from backend
  flashcardId: string
  question: string
}

interface TeachbackResultItem {
  id: string
  status: "pending" | "complete" | "error"
  flashcard_id: string
  question: string
  score: number | null
  correct_points: string[]
  missing_points: string[]
  misconceptions: string[]
  correction_flashcard_id: string | null
  rubric: {
    accuracy: { score: number; evidence: string }
    completeness: { score: number; missed_points: string[] }
    clarity: { score: number; evidence: string }
  } | null
}

async function submitTeachbackAsync(
  flashcardId: string,
  userExplanation: string,
  sessionId: string | null = null,
): Promise<{ id: string }> {
  const res = await fetch(`${API_BASE}/study/teachback/async`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ flashcard_id: flashcardId, user_explanation: userExplanation, session_id: sessionId }),
  })
  if (!res.ok) throw new Error("Teachback submit failed")
  return res.json() as Promise<{ id: string }>
}

async function fetchTeachbackResults(ids: string[]): Promise<TeachbackResultItem[]> {
  if (ids.length === 0) return []
  const res = await fetch(`${API_BASE}/study/teachback/results?ids=${ids.join(",")}`)
  if (!res.ok) throw new Error("Failed to fetch teachback results")
  const data = (await res.json()) as { results: TeachbackResultItem[] }
  return data.results
}

async function fetchSessionTeachbackResults(sessionId: string): Promise<TeachbackResultItem[]> {
  const res = await fetch(`${API_BASE}/study/sessions/${sessionId}/teachback-results`)
  if (!res.ok) return []
  const data = (await res.json()) as { results: TeachbackResultItem[] }
  return data.results
}

// ---------------------------------------------------------------------------
// TeachbackPanel — textarea + submit + results
// ---------------------------------------------------------------------------

interface TeachbackPanelProps {
  card: Flashcard
  onNext: () => void
  onSubmitAsync: (cardId: string, question: string, explanation: string) => void
}

function TeachbackPanel({ card, onNext, onSubmitAsync }: TeachbackPanelProps) {
  const [explanation, setExplanation] = useState("")
  const [isRecording, setIsRecording] = useState(false)
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
  // Tracks whether the current stop was user-initiated (manual) vs natural end.
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
    // Capture values before advancing -- component will unmount on onNext()
    const cardId = card.id
    const question = card.question
    const text = explanation.trim()
    // Fire async submit in parent (runs in background), then advance immediately
    onSubmitAsync(cardId, question, text)
    onNext()
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
        onClick={handleSubmit}
        disabled={!explanation.trim()}
        className="self-start rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        Submit & Next
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
// TeachbackResultsPanel — poll and display async teach-back evaluations
// ---------------------------------------------------------------------------

function scoreBadgeClass(score: number): string {
  if (score >= 80) return "bg-green-100 text-green-700"
  if (score >= 60) return "bg-amber-100 text-amber-700"
  return "bg-red-100 text-red-700"
}

interface TeachbackStats {
  allDone: boolean
  completedCount: number
  avgScore: number
  passCount: number // score >= 60
}

function useTeachbackPolling(pending: PendingTeachback[]): {
  results: TeachbackResultItem[] | undefined
  stats: TeachbackStats
} {
  const realIds = pending
    .map((t) => t.id)
    .filter((id) => !id.startsWith("temp-") && !id.startsWith("error-"))
  const hasUnresolved = pending.some(
    (t) => t.id.startsWith("temp-") || t.id.startsWith("error-")
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
  const avgScore = completed.length > 0
    ? Math.round(completed.reduce((s, r) => s + (r.score ?? 0), 0) / completed.length)
    : 0
  const passCount = completed.filter((r) => (r.score ?? 0) >= 60).length

  return {
    results,
    stats: { allDone, completedCount: completed.length, avgScore, passCount },
  }
}

function TeachbackResultsPanel({ pending, stats, results }: {
  pending: PendingTeachback[]
  stats: TeachbackStats
  results: TeachbackResultItem[] | undefined
}) {
  const hasUnresolved = pending.some(
    (t) => t.id.startsWith("temp-") || t.id.startsWith("error-")
  )

  return (
    <div className="flex w-full max-w-2xl flex-col gap-4">
      {/* Summary bar */}
      {stats.allDone && stats.completedCount > 0 && (
        <div className="rounded-lg border border-border bg-card/50 p-3 text-center">
          <span className="text-sm text-muted-foreground">Average score: </span>
          <span className={`text-lg font-bold ${stats.avgScore >= 80 ? "text-green-600" : stats.avgScore >= 60 ? "text-amber-600" : "text-red-600"}`}>
            {stats.avgScore}/100
          </span>
          <span className="ml-3 text-sm text-muted-foreground">
            ({stats.passCount}/{stats.completedCount} passed)
          </span>
        </div>
      )}

      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-foreground">Teach-Back Results</h3>
        {!stats.allDone && (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 size={12} className="animate-spin" />
            Evaluating...
          </span>
        )}
      </div>

      {pending.map((tb) => {
        // Submit POST failed entirely
        if (tb.id.startsWith("error-")) {
          return (
            <div key={tb.id} className="rounded-lg border border-border bg-muted/30 p-4">
              <p className="text-sm font-medium text-foreground">{tb.question}</p>
              <p className="mt-2 text-xs text-amber-700">Submission failed. Check if Ollama is running.</p>
            </div>
          )
        }

        // POST hasn't completed yet -- still waiting for real ID
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
                Evaluating your explanation...
              </div>
            </div>
          )
        }

        if (result.status === "error") {
          return (
            <div key={tb.id} className="rounded-lg border border-border bg-muted/30 p-4">
              <p className="text-sm font-medium text-foreground">{tb.question}</p>
              <p className="mt-2 text-xs text-amber-700">Evaluation failed. The result could not be generated.</p>
            </div>
          )
        }

        return (
          <div key={tb.id} className="rounded-lg border border-border bg-card p-4">
            <p className="text-sm font-medium text-foreground">{result.question || tb.question}</p>
            <div className="mt-2 flex items-center gap-2">
              <span className={`rounded-full px-3 py-0.5 text-xs font-bold ${scoreBadgeClass(result.score ?? 0)}`}>
                {result.score}/100
              </span>
            </div>

            {result.correct_points.length > 0 && (
              <div className="mt-3 flex flex-col gap-1">
                <p className="text-xs font-semibold text-green-700">Correct</p>
                {result.correct_points.map((p, i) => (
                  <div key={i} className="flex items-start gap-1.5 text-xs text-foreground">
                    <Check size={12} className="mt-0.5 shrink-0 text-green-600" />
                    {p}
                  </div>
                ))}
              </div>
            )}

            {result.missing_points.length > 0 && (
              <div className="mt-3 flex flex-col gap-1">
                <p className="text-xs font-semibold text-amber-700">Missing</p>
                {result.missing_points.map((p, i) => (
                  <div key={i} className="flex items-start gap-1.5 text-xs text-foreground">
                    <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber-500" />
                    {p}
                  </div>
                ))}
              </div>
            )}

            {result.misconceptions.length > 0 && (
              <div className="mt-3 flex flex-col gap-1">
                <p className="text-xs font-semibold text-red-700">Misconceptions</p>
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
      })}
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
  onClear: () => void
  onStartNext: () => void
  pendingTeachbacks: PendingTeachback[]
}

function SessionComplete({
  reviewed, correct, nextReviewDate, onBack, onClear, onStartNext, pendingTeachbacks,
}: SessionCompleteProps) {
  const hasTeachbacks = pendingTeachbacks.length > 0
  const { results, stats } = useTeachbackPolling(pendingTeachbacks)

  // For teach-back mode, derive accuracy from evaluation results
  const displayCorrect = hasTeachbacks ? stats.passCount : correct
  const displayReviewed = hasTeachbacks ? stats.completedCount || reviewed : reviewed
  const pct = displayReviewed === 0 ? 0 : Math.round((displayCorrect / displayReviewed) * 100)
  const showStats = !hasTeachbacks || stats.completedCount > 0

  return (
    <div className="flex flex-col items-center gap-6 overflow-auto px-4 py-6">
      {stats.allDone || !hasTeachbacks ? (
        <h2 className="text-2xl font-bold text-foreground">Session Complete!</h2>
      ) : (
        <h2 className="text-2xl font-bold text-foreground">Evaluating Your Answers...</h2>
      )}

      {showStats && (
        <div className="flex gap-8 text-center">
          <div className="flex flex-col items-center">
            <span className="text-3xl font-bold text-foreground">{displayReviewed}</span>
            <span className="text-sm text-muted-foreground">Cards reviewed</span>
          </div>
          <div className="flex flex-col items-center">
            <span className={`text-3xl font-bold ${pct >= 60 ? "text-green-600" : "text-amber-600"}`}>{pct}%</span>
            <span className="text-sm text-muted-foreground">Passed</span>
          </div>
        </div>
      )}

      {nextReviewDate && (
        <p className="text-sm text-muted-foreground">
          Next review:{" "}
          <span className="font-medium text-foreground">
            {new Date(nextReviewDate).toLocaleDateString()}
          </span>
        </p>
      )}

      {/* Teach-back results section */}
      {hasTeachbacks && (
        <TeachbackResultsPanel pending={pendingTeachbacks} stats={stats} results={results} />
      )}

      <div className="flex items-center gap-3">
        {stats.allDone && hasTeachbacks && (
          <button
            onClick={onStartNext}
            className="rounded bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Start Next Set
          </button>
        )}
        <button
          onClick={onBack}
          className={`rounded px-6 py-2 text-sm font-medium ${
            stats.allDone && hasTeachbacks
              ? "border border-border text-muted-foreground hover:bg-accent"
              : "bg-primary text-primary-foreground hover:bg-primary/90"
          }`}
        >
          Back to Study
        </button>
        {hasTeachbacks && (
          <button
            onClick={onClear}
            className="text-xs text-muted-foreground underline hover:text-foreground"
          >
            Clear Session
          </button>
        )}
      </div>
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
  /** When set, skip card fetching and show results for this session */
  resumeSessionId?: string | null
}

type SessionState = "loading" | "studying" | "complete" | "empty"

export function StudySession({ documentId, collectionId, filters, onExit, resumeSessionId }: StudySessionProps) {
  const [sessionState, setSessionState] = useState<SessionState>("loading")
  const [sessionId, setSessionId] = useState<string | null>(resumeSessionId ?? null)
  const [queue, setQueue] = useState<Flashcard[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [showAnswer, setShowAnswer] = useState(false)
  const [reviewed, setReviewed] = useState(0)
  const [correct, setCorrect] = useState(0)
  const [isRating, setIsRating] = useState(false)
  const [teachbackMode, setTeachbackMode] = useState(!!resumeSessionId)
  // S138: track last rating to show SourcePanel on "again"
  const [lastRating, setLastRating] = useState<Rating | null>(null)
  // Track next review date as minimum due_date across remaining cards
  const [nextReviewDate, setNextReviewDate] = useState<string | null>(null)
  // S155: source context panel state
  const [sourceContext, setSourceContext] = useState<SourceContext | null>(null)
  const [sourceContextLoading, setSourceContextLoading] = useState(false)
  const dismissedSourceContextIds = useRef(new Set<string>())
  // Re-queue: track cards already re-queued to avoid infinite loops (max 1 retry per card)
  const requeuedCardIds = useRef(new Set<string>())
  // Async teach-back: track pending evaluations
  const [pendingTeachbacks, setPendingTeachbacks] = useState<PendingTeachback[]>([])
  // Persisted session tracking
  const { setStudySessionId } = useAppStore()

  // In resume mode, total = remaining cards + already reviewed; in normal mode, queue has all cards
  const [resumedPreviousCount, setResumedPreviousCount] = useState(0)
  const total = queue.length + resumedPreviousCount

  // Resume mode: load previous results + remaining cards
  useEffect(() => {
    if (!resumeSessionId) return
    let cancelled = false

    async function resumeInit() {
      try {
        // Fetch previous results and remaining due cards in parallel
        const [prevResults, cards] = await Promise.all([
          fetchSessionTeachbackResults(resumeSessionId!),
          fetchDueCards(documentId || null, collectionId || null, filters || {}),
        ])
        if (cancelled) return

        // Reconstruct pending teachbacks from previous results
        const previousTeachbacks = prevResults.map((r) => ({
          id: r.id,
          flashcardId: r.flashcard_id,
          question: r.question,
        }))
        setPendingTeachbacks(previousTeachbacks)
        setReviewed(prevResults.length)
        setResumedPreviousCount(prevResults.length)

        // Filter out cards already answered in this session
        const answeredCardIds = new Set(prevResults.map((r) => r.flashcard_id))
        const remainingCards = cards.filter((c) => !answeredCardIds.has(c.id))

        if (remainingCards.length > 0) {
          setQueue(remainingCards)
          setSessionState("studying")
        } else {
          // No remaining cards -- show results
          setSessionState("complete")
        }
      } catch {
        if (!cancelled) setSessionState("complete") // fallback to results view
      }
    }

    void resumeInit()
    return () => { cancelled = true }
  }, [resumeSessionId, documentId, collectionId, filters])

  useEffect(() => {
    if (resumeSessionId) return // skip normal init in resume mode
    let cancelled = false

    async function init() {
      try {
        const [sid, cards] = await Promise.all([
          startSession(documentId ?? null),
          fetchDueCards(documentId || null, collectionId || null, filters || {}),
        ])
        if (cancelled) return
        setSessionId(sid)
        setStudySessionId(sid) // persist for tab-switch recovery
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
  }, [documentId, collectionId, filters, resumeSessionId, setStudySessionId])

  // Teach-back re-queue: poll for completed evaluations during active session
  // and re-add cards with low scores (< 60) to the queue for a second attempt
  const REQUEUE_THRESHOLD = 60
  const realTeachbackIds = pendingTeachbacks
    .map((t) => t.id)
    .filter((id) => !id.startsWith("temp-") && !id.startsWith("error-"))
  const { data: liveResults } = useQuery({
    queryKey: ["teachback-live-poll", ...realTeachbackIds],
    queryFn: () => fetchTeachbackResults(realTeachbackIds),
    refetchInterval: (query) => {
      if (sessionState !== "studying" || !teachbackMode) return false
      const items = query.state.data
      if (!items) return 3000
      return items.some((r) => r.status === "pending") ? 3000 : false
    },
    enabled: sessionState === "studying" && teachbackMode && realTeachbackIds.length > 0,
  })

  // When a teach-back result completes with a low score, re-add the card to the queue
  useEffect(() => {
    if (!liveResults || sessionState !== "studying") return
    for (const r of liveResults) {
      if (
        r.status === "complete" &&
        r.score !== null &&
        r.score < REQUEUE_THRESHOLD &&
        !requeuedCardIds.current.has(r.flashcard_id)
      ) {
        requeuedCardIds.current.add(r.flashcard_id)
        // Find the original card data from the queue or pending teachbacks
        const originalCard = queue.find((c) => c.id === r.flashcard_id)
        if (originalCard) {
          setQueue((prev) => [...prev, originalCard])
        }
      }
    }
  }, [liveResults, sessionState, queue])

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

      // Re-queue "again"-rated cards for a second attempt later in the session
      if (rating === "again" && !requeuedCardIds.current.has(card.id)) {
        requeuedCardIds.current.add(card.id)
        setQueue((prev) => [...prev, card])
      }

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

  function handleTeachbackSubmit(cardId: string, question: string, explanation: string) {
    // Generate a temporary ID for immediate tracking; replace with real ID when POST completes
    const tempId = `temp-${Date.now()}-${cardId}`
    setPendingTeachbacks((prev) => [
      ...prev,
      { id: tempId, flashcardId: cardId, question },
    ])
    // Fire POST in background -- swap temp ID for real ID using tempId as stable key
    void submitTeachbackAsync(cardId, explanation, sessionId)
      .then(({ id }) => {
        setPendingTeachbacks((prev) =>
          prev.map((t) => (t.id === tempId ? { ...t, id } : t))
        )
      })
      .catch((err) => {
        console.warn("Teachback async submit failed", err)
        // Mark as failed so results panel can show an error for this entry
        setPendingTeachbacks((prev) =>
          prev.map((t) => (t.id === tempId ? { ...t, id: `error-${tempId}` } : t))
        )
      })
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
      // Keep teachbackMode -- don't reset between cards
    }
  }

  async function handleBackToStudy() {
    if (sessionId && sessionState !== "complete") {
      await endSession(sessionId)
    }
    // If there are pending teach-back evaluations, show the results screen
    // instead of exiting so the user can see their results
    if (pendingTeachbacks.length > 0) {
      setSessionState("complete")
    } else {
      onExit()
    }
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
      <div className="flex h-full items-center justify-center overflow-auto py-8">
        <SessionComplete
          reviewed={reviewed}
          correct={correct}
          nextReviewDate={nextReviewDate}
          onBack={onExit}
          onClear={() => {
            setStudySessionId(null)
            onExit()
          }}
          onStartNext={() => {
            // Reset session state for a new round; keep studySessionId for continuity
            setQueue([])
            setCurrentIndex(0)
            setReviewed(0)
            setCorrect(0)
            setPendingTeachbacks([])
            setResumedPreviousCount(0)
            requeuedCardIds.current.clear()
            setSessionState("loading")
            // Re-trigger init by creating a new session
            void (async () => {
              try {
                const [sid, cards] = await Promise.all([
                  startSession(documentId ?? null),
                  fetchDueCards(documentId || null, collectionId || null, filters || {}),
                ])
                setSessionId(sid)
                setStudySessionId(sid)
                setQueue(cards)
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

  return (
    <div className="flex h-full flex-col items-center gap-6 overflow-auto px-6 py-8">
      <ProgressBar done={reviewed} total={total} />

      {/* Mode toggle -- locked once a teach-back or rating has been submitted */}
      {reviewed === 0 && pendingTeachbacks.length === 0 ? (
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
      ) : (
        <div className="rounded-md border border-border px-4 py-1.5 text-sm font-medium text-foreground">
          {teachbackMode ? "Teach-back" : "Flashcard"} mode
        </div>
      )}

      {teachbackMode ? (
        <TeachbackPanel key={currentCard.id} card={currentCard} onNext={handleTeachbackNext} onSubmitAsync={handleTeachbackSubmit} />
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
