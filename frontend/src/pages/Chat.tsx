import { useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, BookMarked, BookOpen, Globe, Loader2, Send, Trash2, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { GapResultCard } from "@/components/GapResultCard"
import type { GapCardData } from "@/components/GapResultCard"
import { QuizQuestionCard } from "@/components/QuizQuestionCard"
import { TeachBackResultCard } from "@/components/TeachBackResultCard"
import type { TeachBackCardData } from "@/components/TeachBackResultCard"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { Skeleton } from "@/components/ui/skeleton"
import { logger } from "@/lib/logger"
import { useAppStore } from "@/store"

import { API_BASE } from "@/lib/config"

// ---------------------------------------------------------------------------
// ExploreConnectionsChips — graph-derived entity-pair suggestions (S109)
// ---------------------------------------------------------------------------

interface ExplorationSuggestion {
  text: string
  entity_names: string[]
}

interface ExploreConnectionsChipsProps {
  documentId: string
  onSuggest: (text: string) => void
}

function ExploreConnectionsChips({ documentId, onSuggest }: ExploreConnectionsChipsProps) {
  const { data, isLoading, isError } = useQuery<ExplorationSuggestion[]>({
    queryKey: ["explorations", documentId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/chat/explorations?document_id=${encodeURIComponent(documentId)}`)
      if (!res.ok) throw new Error("Failed to fetch explorations")
      return res.json() as Promise<ExplorationSuggestion[]>
    },
    staleTime: 120_000,
  })

  if (isError) return null
  if (isLoading) {
    return (
      <div className="flex flex-wrap gap-2 border-t border-border px-6 py-3">
        <span className="text-xs text-muted-foreground">Explore connections:</span>
        <div className="h-7 w-40 animate-pulse rounded-full bg-muted" />
        <div className="h-7 w-40 animate-pulse rounded-full bg-muted" />
      </div>
    )
  }
  if (!data || data.length === 0) return null

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-border px-6 py-3">
      <span className="text-xs text-muted-foreground">Explore connections:</span>
      {data.map((s) => (
        <button
          key={s.text}
          onClick={() => onSuggest(s.text)}
          className="truncate max-w-[240px] rounded-full border border-primary/30 bg-primary/5 px-3 py-1.5 text-xs text-primary hover:bg-primary/10 transition-colors"
        >
          {s.text}
        </button>
      ))}
    </div>
  )
}

interface DocListItem {
  id: string
  title: string
}

async function fetchDocList(): Promise<DocListItem[]> {
  const res = await fetch(`${API_BASE}/documents?sort=newest&page=1&page_size=100`)
  if (!res.ok) return []
  const data = (await res.json()) as { items: DocListItem[] }
  return data.items ?? []
}

interface Citation {
  document_title: string | null
  section_heading: string
  page: number
  excerpt: string
  version_mismatch?: boolean  // S142: local vs web version discrepancy
}

interface WebSource {
  url: string
  title: string
  content: string
  domain: string
  version_info: string
}

// S148: chunk-derived source citations for deep-link navigation
interface SourceCitation {
  chunk_id: string
  document_id: string
  document_title: string
  section_id: string | null
  section_heading: string
  pdf_page_number: number | null
}

interface WebSearchSettings {
  provider: string
  enabled: boolean
}

type Confidence = "high" | "medium" | "low"

interface QuizCardData {
  type: "quiz_question"
  question: string
  context_hint: string
  document_id: string
  error?: string
}

type AnyCardData = GapCardData | QuizCardData | TeachBackCardData

interface ChatMessage {
  id: string
  role: "user" | "assistant"
  text: string
  type?: "text" | "card"
  cardData?: AnyCardData
  citations?: Citation[]
  confidence?: Confidence
  not_found?: boolean
  isStreaming?: boolean
  image_ids?: string[]
  web_sources?: WebSource[]  // S142: web augmentation sources
  source_citations?: SourceCitation[]  // S148: chunk-derived deep-link citations
}

interface ConfusionSignal {
  concept: string
  count: number
  last_asked: string
}

interface SessionPlanItem {
  type: "review" | "gap" | "read"
  title: string
  minutes: number
  action_label: string
  action_target: string
}

interface SessionPlanResponse {
  total_minutes: number
  items: SessionPlanItem[]
}

interface CloudProvider {
  name: string
  available: boolean
}

interface LLMSettings {
  processing_mode: string
  active_model: string
  available_local_models: string[]
  cloud_providers: CloudProvider[]
}

async function fetchLLMSettings(): Promise<LLMSettings> {
  const res = await fetch(`${API_BASE}/settings/llm`)
  if (!res.ok) throw new Error("Failed to fetch LLM settings")
  return res.json() as Promise<LLMSettings>
}

const CONFIDENCE_BADGE: Record<Confidence, "green" | "blue" | "gray"> = {
  high: "green",
  medium: "blue",
  low: "gray",
}

const EXAMPLE_QUESTIONS = [
  "What are the main themes?",
  "Summarize the key findings.",
  "What conclusions are drawn?",
]

export function getContextualSuggestions(dueCount: number): string[] {
  // The plan pill must always appear as the 4th item per S101 AC.
  // When dueCount > 0 the due-review pill occupies slot 0, so we drop
  // "Quiz me on the key concepts" to keep total at 4.
  const pills: string[] = []
  if (dueCount > 0) pills.push(`Review my ${dueCount} due flashcards`)
  pills.push("Find gaps in my notes")
  pills.push("Summarize this for me")
  if (dueCount === 0) pills.push("Quiz me on the key concepts")
  pills.push("__plan__Plan my session")
  return pills.slice(0, 4)
}

interface ChatSuggestionsProps {
  activeDocumentId: string
  onSuggest: (text: string) => void
  onPlan: () => void
}

function ChatSuggestions({ activeDocumentId, onSuggest, onPlan }: ChatSuggestionsProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["due-pills", activeDocumentId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/study/due?document_id=${encodeURIComponent(activeDocumentId)}`)
      if (!res.ok) throw new Error("Failed to fetch due cards")
      return res.json() as Promise<unknown[]>
    },
    staleTime: 60_000,
  })

  if (isError) return null

  if (isLoading) {
    return (
      <div className="flex flex-wrap gap-2 border-t border-border px-6 py-3">
        <div className="h-7 w-32 animate-pulse rounded-full bg-muted" />
        <div className="h-7 w-32 animate-pulse rounded-full bg-muted" />
      </div>
    )
  }

  const dueCount = (data ?? []).length
  const suggestions = getContextualSuggestions(dueCount)

  return (
    <div className="flex flex-wrap gap-2 border-t border-border px-6 py-3">
      {suggestions.map((s) => {
        const isPlan = s.startsWith("__plan__")
        const displayText = isPlan ? s.slice(8) : s
        return (
          <button
            key={s}
            onClick={() => { if (isPlan) { onPlan() } else { onSuggest(s) } }}
            className="truncate max-w-[200px] rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
          >
            {displayText}
          </button>
        )
      })}
    </div>
  )
}

type AddButtonState = "idle" | "loading" | "done" | "error"

function ConfusionBanner({
  signal,
  onDismiss,
  onAdded,
}: {
  signal: ConfusionSignal
  onDismiss: () => void
  onAdded: () => void
}) {
  const [addState, setAddState] = useState<AddButtonState>("idle")
  const [addError, setAddError] = useState<string | null>(null)

  async function handleAdd() {
    setAddState("loading")
    setAddError(null)
    try {
      const res = await fetch(`${API_BASE}/flashcards/from-gaps`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gaps: [signal.concept], document_id: "" }),
      })
      if (res.status === 503) {
        setAddError("Ollama is unavailable. Start it with: ollama serve")
        setAddState("error")
        return
      }
      if (!res.ok) {
        setAddError("Failed to add flashcard. Please try again.")
        setAddState("error")
        return
      }
      setAddState("done")
      onAdded()
    } catch {
      setAddError("Network error. Please try again.")
      setAddState("error")
    }
  }

  return (
    <div className="mx-6 mt-2 flex items-center justify-between rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-950">
      <span className="text-xs text-amber-800 dark:text-amber-200">
        You have asked about &ldquo;{signal.concept}&rdquo; {signal.count} times. Add it to your flashcards?
      </span>
      <div className="ml-3 flex shrink-0 items-center gap-2">
        {addError ? (
          <span className="text-xs text-red-600">{addError}</span>
        ) : null}
        {addState !== "done" && (
          <button
            onClick={() => void handleAdd()}
            disabled={addState === "loading"}
            className="inline-flex items-center gap-1 rounded-md border border-amber-300 px-2 py-1 text-xs text-amber-800 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-700 dark:text-amber-200 dark:hover:bg-amber-900"
          >
            {addState === "loading" ? (
              <Loader2 size={12} className="animate-spin" />
            ) : addState === "error" ? (
              "Retry"
            ) : (
              "Add to Flashcards"
            )}
          </button>
        )}
        <button
          onClick={onDismiss}
          className="rounded p-0.5 text-amber-600 hover:bg-amber-100 dark:text-amber-300 dark:hover:bg-amber-900"
          aria-label="Dismiss"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  )
}

function buildModelOptions(settings: LLMSettings | undefined): string[] {
  if (!settings) return []
  // Cloud mode: backend handles routing via get_effective_routing(); no model selector needed.
  if (settings.processing_mode === "cloud") return []
  const opts = settings.available_local_models
  return opts.length > 0 ? opts : (settings.active_model ? [settings.active_model] : [])
}

export default function Chat() {
  const activeDocumentId = useAppStore((s) => s.activeDocumentId)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const chatPreload = useAppStore((s) => s.chatPreload)
  const clearChatPreload = useAppStore((s) => s.clearChatPreload)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const qc = useQueryClient()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [scope, setScope] = useState<"single" | "all">("all")
  // selectedDocId: explicit in-tab selection; falls back to global activeDocumentId
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)
  const [model, setModel] = useState<string>("")
  const [isStreaming, setIsStreaming] = useState(false)
  const [qaError, setQaError] = useState<string | null>(null)
  const [dismissedSignals, setDismissedSignals] = useState<Set<string>>(new Set())
  const [webEnabled, setWebEnabled] = useState(false)
  const [webCallsUsed, setWebCallsUsed] = useState(0)
  const [showPlanPanel, setShowPlanPanel] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const mountTime = useRef(Date.now())

  // Document list for the "This document" picker
  const { data: docList } = useQuery({
    queryKey: ["chat-doc-list"],
    queryFn: fetchDocList,
    staleTime: 30_000,
  })

  // Pre-populate from global store when user arrives from Learning tab
  useEffect(() => {
    if (activeDocumentId) {
      setSelectedDocId((prev) => prev ?? activeDocumentId)
    }
  }, [activeDocumentId])

  // S147: Pre-fill input from chatPreload set by SelectionActionBar "Ask in Chat" action
  useEffect(() => {
    if (chatPreload) {
      setInput(chatPreload.text)
      if (chatPreload.documentId) {
        setSelectedDocId(chatPreload.documentId)
        setScope("single")
      }
      clearChatPreload()
      setTimeout(() => textareaRef.current?.focus(), 50)
    }
  }, [chatPreload, clearChatPreload])

  // Pre-fill input from ?q= query param (e.g. from Notes "Compare with Book" button)
  useEffect(() => {
    const prefill = searchParams.get("q")
    if (prefill) {
      setInput(prefill)
    }
  }, [searchParams])

  const { data: llmSettings, isLoading: llmLoading, isError: llmError } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: fetchLLMSettings,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  })

  const { data: confusionSignals } = useQuery<ConfusionSignal[]>({
    queryKey: ["confusion-signals"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/chat/confusion-signals`)
      if (!res.ok) throw new Error("Failed to fetch confusion signals")
      return res.json() as Promise<ConfusionSignal[]>
    },
    staleTime: 300_000,
  })

  const { data: webSearchSettings } = useQuery<WebSearchSettings>({
    queryKey: ["web-search-settings"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/settings/web-search`)
      if (!res.ok) throw new Error("Failed to fetch web search settings")
      return res.json() as Promise<WebSearchSettings>
    },
    staleTime: 300_000,
    refetchOnWindowFocus: false,
  })

  const {
    data: sessionPlan,
    isLoading: planLoading,
    isError: planError,
    refetch: refetchPlan,
  } = useQuery<SessionPlanResponse>({
    queryKey: ["session-plan"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/study/session-plan?minutes=20`)
      if (!res.ok) throw new Error("Failed to fetch session plan")
      return res.json() as Promise<SessionPlanResponse>
    },
    enabled: showPlanPanel,
    staleTime: 60_000,
  })

  const modelOptions = buildModelOptions(llmSettings)

  // Check if any documents have been ingested (use prefetched cache if available)
  const cachedDocs = qc.getQueryData<{ items?: unknown[] } | unknown[]>(
    ["documents", undefined, null, "newest", 1, 20],
  )
  const hasDocuments = Array.isArray(cachedDocs)
    ? cachedDocs.length > 0
    : (cachedDocs as { items?: unknown[] } | undefined)?.items?.length !== 0

  useEffect(() => {
    logger.info("[Chat] mounted")
  }, [])

  useEffect(() => {
    if (llmSettings && !model) {
      const elapsed = Date.now() - mountTime.current
      logger.info("[Chat] loaded", { duration_ms: elapsed })
      setModel(llmSettings.active_model)
    }
  }, [llmSettings, model])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  function clearConversation() {
    setMessages([])
    setQaError(null)
    setWebCallsUsed(0)
  }

  function autoResize() {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = "auto"
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`
  }

  async function sendMessage(question: string) {
    if (!question.trim() || isStreaming) return
    setInput("")
    if (textareaRef.current) textareaRef.current.style.height = "auto"

    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", text: question }
    const assistantId = crypto.randomUUID()
    const assistantMsg: ChatMessage = { id: assistantId, role: "assistant", text: "", isStreaming: true }
    setMessages((m) => [...m, userMsg, assistantMsg])
    setIsStreaming(true)

    try {
      const effectiveDocId = selectedDocId ?? activeDocumentId
      const documentIds = scope === "single" && effectiveDocId ? [effectiveDocId] : null

      // Collect last 6 completed messages (3 exchanges) as conversation history.
      // Excludes the current streaming placeholder and not_found messages.
      const historySlice = messages
        .filter((m) => !m.isStreaming && !m.not_found && m.text)
        .slice(-6)
        .map((m) => ({ role: m.role, content: m.text }))

      const res = await fetch(`${API_BASE}/qa`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          document_ids: documentIds,
          scope,
          model: model || null,
          messages: historySlice.length > 0 ? historySlice : undefined,
          web_enabled: webEnabled,
        }),
      })
      if (!res.ok || !res.body) throw new Error("QA request failed")

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() ?? ""

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue
          try {
            const payload = JSON.parse(line.slice(6)) as Record<string, unknown>

            // __card__ protocol: a card event replaces the streaming placeholder with a card message.
            // No token events follow a card event -- the done event closes the stream.
            if (payload["card"] !== undefined) {
              const cardData = payload["card"] as AnyCardData
              setMessages((m) =>
                m.map((msg) =>
                  msg.id === assistantId
                    ? { ...msg, type: "card" as const, cardData, isStreaming: false, text: "" }
                    : msg,
                ),
              )
            }

            if (typeof payload["token"] === "string") {
              const token = payload["token"] as string
              setMessages((m) =>
                m.map((msg) =>
                  msg.id === assistantId ? { ...msg, text: msg.text + token } : msg,
                ),
              )
            }

            // SSE error event — end streaming, remove placeholder, show banner
            if (typeof payload["error"] === "string") {
              const errorCode = payload["error"] as string
              const fallbackMsg = (payload["message"] as string | undefined) ?? "An error occurred."
              const errorMsg =
                errorCode === "llm_unavailable"
                  ? "Ollama is not running. Start it with: ollama serve"
                  : errorCode === "no_context"
                  ? "No relevant content found. Make sure at least one document has been ingested."
                  : fallbackMsg
              setIsStreaming(false)
              setMessages((m) => m.filter((msg) => msg.id !== assistantId))
              setQaError(errorMsg)
              break
            }

            if (payload["done"] === true) {
              const not_found = payload["not_found"] === true
              const finalAnswer = typeof payload["answer"] === "string" ? payload["answer"] : undefined
              const citations = (payload["citations"] as Citation[] | undefined) ?? []
              const confidence = (payload["confidence"] as Confidence | undefined) ?? "low"
              const image_ids = (payload["image_ids"] as string[] | undefined) ?? []
              const web_sources = (payload["web_sources"] as WebSource[] | undefined) ?? []
              const source_citations = (payload["source_citations"] as SourceCitation[] | undefined) ?? []
              const newWebCallsUsed = (payload["web_calls_used"] as number | undefined) ?? webCallsUsed
              setWebCallsUsed(newWebCallsUsed)
              setMessages((m) =>
                m.map((msg) =>
                  msg.id === assistantId
                    ? {
                        ...msg,
                        // Replace streamed tokens with clean parsed answer from backend.
                        // This removes any citation JSON fragments that leaked during streaming.
                        text: finalAnswer !== undefined ? finalAnswer : msg.text,
                        isStreaming: false,
                        citations,
                        confidence,
                        not_found,
                        image_ids,
                        web_sources,
                        source_citations,
                      }
                    : msg,
                ),
              )
              setIsStreaming(false)
            }
          } catch {
            // skip malformed SSE event
          }
        }
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err)
      logger.error("[Chat] fetch failed", { endpoint: "/qa", error: errMsg })
      setQaError(
        errMsg.includes("Failed to fetch") || errMsg.includes("NetworkError")
          ? "Cannot reach the server. Is the backend running on port 7820?"
          : `Could not get a response: ${errMsg}`
      )
      setMessages((m) => m.filter((msg) => msg.id !== assistantId))
      setIsStreaming(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      void sendMessage(input)
    }
  }

  // S148: navigate to Learning tab with DocumentReader open at the cited section/page
  function navigateToCitation(c: SourceCitation) {
    setActiveDocument(c.document_id)
    const params = new URLSearchParams()
    params.set("doc", c.document_id)
    if (c.section_id) params.set("section_id", c.section_id)
    if (c.pdf_page_number) params.set("page", String(c.pdf_page_number))
    navigate(`/learning?${params.toString()}`)
  }

  const effectiveDocId = selectedDocId ?? activeDocumentId
  const noDocumentSelected = scope === "single" && !effectiveDocId

  return (
    <div className="flex h-full flex-col">
      {/* Header controls */}
      <div className="flex items-center gap-4 border-b border-border px-6 py-3">
        {/* Scope selector */}
        <div className="flex items-center rounded-md border border-border">
          <button
            onClick={() => { if (scope !== "single") { setScope("single"); clearConversation() } }}
            className={`rounded-l-md px-3 py-1.5 text-xs font-medium transition-colors ${scope === "single" ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/50"}`}
          >
            This document
          </button>
          <button
            onClick={() => { if (scope !== "all") { setScope("all"); clearConversation() } }}
            className={`rounded-r-md px-3 py-1.5 text-xs font-medium transition-colors ${scope === "all" ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/50"}`}
          >
            All my content
          </button>
        </div>

        {/* Document picker — only visible in "This document" scope */}
        {scope === "single" && (
          <select
            value={effectiveDocId ?? ""}
            onChange={(e) => { setSelectedDocId(e.target.value || null); clearConversation() }}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring max-w-[220px]"
          >
            <option value="">Select a document…</option>
            {(docList ?? []).map((doc) => (
              <option key={doc.id} value={doc.id}>{doc.title}</option>
            ))}
          </select>
        )}

        {/* Clear conversation button — only shown when there are messages */}
        {messages.length > 0 && !isStreaming && (
          <button
            onClick={clearConversation}
            className="ml-auto flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
            title="Clear conversation"
          >
            <Trash2 size={13} />
            Clear
          </button>
        )}

        {/* Model selector */}
        {llmLoading ? (
          <Skeleton className="h-8 w-36" />
        ) : modelOptions.length > 0 ? (
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {modelOptions.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        ) : null}

        {/* Web search toggle (S142) */}
        <div
          title={
            webSearchSettings?.enabled
              ? "Toggle web augmentation (adds current web results to low-confidence answers)"
              : "Configure a web search provider in Settings to enable web search"
          }
        >
          <button
            disabled={!webSearchSettings?.enabled}
            onClick={() => setWebEnabled((prev) => !prev)}
            className={`flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs transition-colors ${
              webEnabled
                ? "border-blue-300 bg-blue-50 text-blue-700"
                : "border-border text-muted-foreground hover:bg-accent"
            } disabled:cursor-not-allowed disabled:opacity-50`}
          >
            <Globe size={12} />
            Web
          </button>
        </div>

        {/* Web call counter -- shown when web is enabled and conversation is active */}
        {webEnabled && messages.length > 0 && (
          <span className="text-xs text-muted-foreground">Web: {webCallsUsed}/3</span>
        )}
      </div>

      {/* LLM settings unavailable warning */}
      {llmError && (
        <div className="mx-6 mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          LLM settings unavailable — using defaults
        </div>
      )}

      {/* QA error banner — inline amber alert */}
      {qaError && (
        <div className="mx-6 mt-2 flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <span className="flex-1">{qaError}</span>
          <button onClick={() => setQaError(null)} className="hover:text-amber-900" aria-label="Dismiss">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Confusion nudge banners -- one per un-dismissed signal with count >= 3 */}
      {(confusionSignals ?? [])
        .filter((s) => s.count >= 3 && !dismissedSignals.has(s.concept))
        .map((signal) => (
          <ConfusionBanner
            key={signal.concept}
            signal={signal}
            onDismiss={() => {
              setDismissedSignals((prev) => new Set([...prev, signal.concept]))
            }}
            onAdded={() => {
              setDismissedSignals((prev) => new Set([...prev, signal.concept]))
            }}
          />
        ))}

      {/* Message list */}
      <div className="flex-1 overflow-auto px-6 py-4">
        {llmLoading ? (
          <div className="flex flex-col gap-3 py-4">
            <Skeleton className="h-10 w-3/4 self-end" />
            <Skeleton className="h-16 w-2/3" />
            <Skeleton className="h-10 w-1/2 self-end" />
          </div>
        ) : noDocumentSelected ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-muted-foreground">
              Open a document in the Learning tab to ask questions about it.
            </p>
          </div>
        ) : messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4">
            {hasDocuments === false ? (
              <p className="max-w-xs text-center text-sm text-muted-foreground">
                Upload a document in the Learning tab to start chatting about it.
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">Ask a question to get started.</p>
            )}
            <div className="flex flex-wrap justify-center gap-2">
              {EXAMPLE_QUESTIONS.map((q) => (
                <button
                  key={q}
                  onClick={() => void sendMessage(q)}
                  className="rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[80%] rounded-lg px-4 py-3 ${
                    msg.role === "user"
                      ? "bg-slate-100 text-slate-900"
                      : "border border-border bg-white text-foreground shadow-sm"
                  }`}
                >
                  {msg.type === "card" && msg.cardData !== undefined ? (
                    msg.cardData.type === "quiz_question" ? (
                      <QuizQuestionCard
                        question={(msg.cardData as QuizCardData).question}
                        contextHint={(msg.cardData as QuizCardData).context_hint}
                        documentId={(msg.cardData as QuizCardData).document_id}
                        error={(msg.cardData as QuizCardData).error}
                        onSubmit={sendMessage}
                      />
                    ) : msg.cardData.type === "teach_back_result" ? (
                      <TeachBackResultCard data={msg.cardData as TeachBackCardData} />
                    ) : msg.cardData.type === "gap_result" ? (
                      <GapResultCard data={msg.cardData as GapCardData} documentId={effectiveDocId ?? undefined} />
                    ) : (
                      <p className="text-xs text-muted-foreground">Unknown card type</p>
                    )
                  ) : msg.not_found ? (
                    <p className="text-sm text-blue-600">
                      This information was not found in the selected content.
                    </p>
                  ) : msg.role === "user" ? (
                    <p className="whitespace-pre-wrap text-sm">{msg.text}</p>
                  ) : msg.isStreaming && msg.text === "" ? (
                    // Skeleton shown while waiting for a card SSE event (e.g. quiz, teach-back, gap)
                    // or before the first token of a streamed text response arrives.
                    <div className="flex flex-col gap-2">
                      <Skeleton className="h-4 w-48" />
                      <Skeleton className="h-4 w-64" />
                      <Skeleton className="h-4 w-40" />
                    </div>
                  ) : (
                    <div className="[&_p]:text-sm [&_p]:leading-relaxed [&_p]:my-1
                      [&_ol]:text-sm [&_ol]:my-1 [&_ol]:pl-5 [&_ol]:list-decimal
                      [&_ul]:text-sm [&_ul]:my-1 [&_ul]:pl-5 [&_ul]:list-disc
                      [&_li]:my-0.5
                      [&_strong]:font-semibold
                      [&_h1]:text-base [&_h1]:font-semibold [&_h1]:mt-2 [&_h1]:mb-1
                      [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:mt-2 [&_h2]:mb-1
                      [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:mt-1">
                      <MarkdownRenderer>{msg.text}</MarkdownRenderer>
                      {msg.isStreaming && <span className="animate-pulse">▍</span>}
                    </div>
                  )}

                  {/* Citations and confidence — shown after streaming completes */}
                  {!msg.isStreaming && msg.citations && msg.citations.length > 0 && (
                    <div className="mt-3 space-y-2">
                      <div className="flex flex-wrap gap-1.5">
                        {msg.citations.map((c, i) => (
                          <span
                            key={i}
                            className="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                            title={c.excerpt}
                          >
                            {c.document_title
                              ? `${c.document_title.slice(0, 20)}${c.document_title.length > 20 ? "…" : ""} · p.${c.page}`
                              : `p.${c.page}`}
                            {c.version_mismatch && (
                              <span className="ml-1 rounded-full border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">
                                Version mismatch
                              </span>
                            )}
                          </span>
                        ))}
                      </div>
                      {msg.confidence && (
                        <Badge variant={CONFIDENCE_BADGE[msg.confidence]}>
                          {msg.confidence} confidence
                        </Badge>
                      )}
                    </div>
                  )}

                  {/* Web sources — shown after streaming completes (S142) */}
                  {!msg.isStreaming && msg.web_sources && msg.web_sources.length > 0 && (
                    <div className="mt-2 space-y-1">
                      <span className="text-xs font-medium text-muted-foreground">Web sources:</span>
                      {msg.web_sources.map((s, i) => (
                        <a
                          key={i}
                          href={s.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="block truncate text-xs text-blue-600 hover:underline"
                          title={s.title}
                        >
                          [Web: {s.domain}] {s.title}
                        </a>
                      ))}
                    </div>
                  )}

                  {/* Source citations — deep-links to exact section/page (S148) */}
                  {!msg.isStreaming && msg.source_citations && msg.source_citations.length > 0 && (
                    <div className="mt-3 space-y-1">
                      <span className="text-xs font-medium text-muted-foreground">Sources:</span>
                      <div className="flex flex-wrap gap-1.5 mt-1">
                        {msg.source_citations.map((c, i) => {
                          const titleAbbrev = c.document_title
                            ? `${c.document_title.slice(0, 20)}${c.document_title.length > 20 ? "..." : ""}`
                            : "Doc"
                          const headingAbbrev = c.section_heading
                            ? ` / ${c.section_heading.slice(0, 30)}${c.section_heading.length > 30 ? "..." : ""}`
                            : ""
                          const pageLabel = c.pdf_page_number ? ` (p.${c.pdf_page_number})` : ""
                          return (
                            <button
                              key={i}
                              onClick={() => navigateToCitation(c)}
                              className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/5 px-2.5 py-0.5 text-xs text-primary hover:bg-primary/10 transition-colors animate-in fade-in duration-300"
                              title={`${c.document_title} — ${c.section_heading}`}
                            >
                              {titleAbbrev}{headingAbbrev}{pageLabel}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* Image thumbnails — shown when retrieval matched image descriptions (S134) */}
                  {!msg.isStreaming && msg.image_ids && msg.image_ids.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {msg.image_ids.map((id) => (
                        <img
                          key={id}
                          src={`${API_BASE}/images/${id}/raw`}
                          alt="Diagram from document"
                          className="h-24 w-auto rounded border border-border object-contain"
                          loading="lazy"
                          onError={(e) => {
                            // Hide the broken image element if the file is missing on disk
                            ;(e.currentTarget as HTMLImageElement).style.display = "none"
                          }}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Contextual suggestion pills — only shown before conversation starts */}
      {messages.length === 0 && activeDocumentId && (
        <ChatSuggestions
          activeDocumentId={activeDocumentId}
          onSuggest={(text) => void sendMessage(text)}
          onPlan={() => setShowPlanPanel(true)}
        />
      )}

      {/* Graph-derived exploration chips — scope=single, document selected, chat empty (S109) */}
      {messages.length === 0 && scope === "single" && effectiveDocId && (
        <ExploreConnectionsChips
          documentId={effectiveDocId}
          onSuggest={(text) => void sendMessage(text)}
        />
      )}

      {/* Session plan slide-up panel — positioned above the input area */}
      <div
        className={`border-t border-border bg-background transition-[max-height,opacity] duration-300 ease-in-out overflow-hidden ${showPlanPanel ? "max-h-96 opacity-100" : "max-h-0 opacity-0 pointer-events-none"}`}
      >
        {/* Panel header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-3">
          <span className="text-sm font-medium">
            Your study plan ({sessionPlan?.total_minutes ?? 20} min)
          </span>
          <button
            onClick={() => setShowPlanPanel(false)}
            className="rounded p-0.5 text-muted-foreground hover:bg-accent"
            aria-label="Close plan panel"
          >
            <X size={14} />
          </button>
        </div>
        {/* Panel body */}
        <div className="px-6 py-3">
          {planLoading ? (
            <div className="flex flex-col gap-2">
              <div className="h-10 animate-pulse rounded bg-muted" />
              <div className="h-10 animate-pulse rounded bg-muted" />
              <div className="h-10 animate-pulse rounded bg-muted" />
            </div>
          ) : planError ? (
            <div className="flex items-center gap-3 text-sm text-destructive">
              <span>Could not load your study plan. Try again.</span>
              <button
                onClick={() => void refetchPlan()}
                className="rounded border border-destructive px-2 py-0.5 text-xs hover:bg-destructive/10"
              >
                Retry
              </button>
            </div>
          ) : !sessionPlan || sessionPlan.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">No study tasks found. You are all caught up!</p>
          ) : (
            <div className="flex flex-col gap-2">
              {sessionPlan.items.map((item, idx) => (
                <div key={idx} className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                  <div className="flex items-center gap-2">
                    {item.type === "review" ? (
                      <BookOpen size={14} className="shrink-0 text-blue-500" />
                    ) : item.type === "gap" ? (
                      <AlertTriangle size={14} className="shrink-0 text-amber-500" />
                    ) : (
                      <BookMarked size={14} className="shrink-0 text-green-500" />
                    )}
                    <span className="text-sm">{item.title}</span>
                    <span className="rounded bg-muted px-1 text-xs text-muted-foreground">{item.minutes} min</span>
                  </div>
                  <button
                    onClick={() => { navigate(item.action_target) }}
                    className="ml-3 shrink-0 rounded border border-border px-2 py-0.5 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                  >
                    {item.action_label}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Input area */}
      <div className="border-t border-border px-6 py-4">
        <div className="flex items-end gap-3">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value)
              autoResize()
            }}
            onKeyDown={handleKeyDown}
            placeholder={noDocumentSelected ? "Select a document first..." : "Ask a question..."}
            disabled={noDocumentSelected || isStreaming}
            rows={1}
            className="flex-1 resize-none rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
          />
          <button
            onClick={() => void sendMessage(input)}
            disabled={!input.trim() || isStreaming || noDocumentSelected}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
          >
            <Send size={14} />
          </button>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">Enter to send · Shift+Enter for newline</p>
      </div>
    </div>
  )
}
