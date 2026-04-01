import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, BookMarked, BookOpen, ChevronDown, Globe, Info, Send, Settings, Trash2, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { SourceCitationChips } from "@/components/SourceCitationChips"
import type { SourceCitation } from "@/components/SourceCitationChips"
import { GapResultCard } from "@/components/GapResultCard"
import type { GapCardData } from "@/components/GapResultCard"
import { QuizQuestionCard } from "@/components/QuizQuestionCard"
import { TeachBackResultCard } from "@/components/TeachBackResultCard"
import type { TeachBackCardData } from "@/components/TeachBackResultCard"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { ChatSettingsDrawer } from "@/components/ChatSettingsDrawer"
import { Skeleton } from "@/components/ui/skeleton"
import { logger } from "@/lib/logger"
import { useAppStore } from "@/store"
import { buildModelOptions, buildScopeComboboxLabel, TRANSPARENCY_DEFAULT_OPEN } from "@/lib/chatSettingsUtils"

import { API_BASE } from "@/lib/config"

// ---------------------------------------------------------------------------
// SuggestionPills — two-phase: show cached instantly, refresh with LLM in background
// ---------------------------------------------------------------------------

interface SuggestionPillsProps {
  documentId: string | null
  onSuggest: (text: string) => void
}

interface SuggestionItem {
  id: string
  text: string
}

interface SuggestionsResponse {
  suggestions: SuggestionItem[]
}

function SuggestionPills({ documentId, onSuggest }: SuggestionPillsProps) {
  const qc = useQueryClient()

  // Phase 1: Instant — fetch from DB cache (no LLM, sub-50ms)
  const { data: cached } = useQuery<SuggestionsResponse>({
    queryKey: ["chat-suggestions-cached", documentId],
    queryFn: async () => {
      const url = documentId
        ? `${API_BASE}/chat/suggestions/cached?document_id=${encodeURIComponent(documentId)}`
        : `${API_BASE}/chat/suggestions/cached`
      const res = await fetch(url)
      if (!res.ok) throw new Error("Failed to fetch cached suggestions")
      return res.json() as Promise<SuggestionsResponse>
    },
    staleTime: 30_000,
  })

  // Phase 2: Background refresh — LLM-generated (may take seconds)
  const { data: fresh } = useQuery<SuggestionsResponse>({
    queryKey: ["chat-suggestions", documentId],
    queryFn: async () => {
      const url = documentId
        ? `${API_BASE}/chat/suggestions?document_id=${encodeURIComponent(documentId)}`
        : `${API_BASE}/chat/suggestions`
      const res = await fetch(url)
      if (!res.ok) throw new Error("Failed to fetch suggestions")
      const result = res.json() as Promise<SuggestionsResponse>
      // Once fresh data arrives, also update the cached query so next switch is instant
      result.then((data) => {
        qc.setQueryData(["chat-suggestions-cached", documentId], data)
      }).catch(() => { })
      return result
    },
    staleTime: 0,
  })

  // Use fresh data if available, otherwise cached
  const data = fresh ?? cached
  const hasSuggestions = data && data.suggestions.length > 0
  const isInitialLoading = !cached && !fresh

  if (isInitialLoading) {
    return (
      <div className="flex flex-wrap gap-2 border-t border-border px-6 py-3">
        <div className="h-7 w-40 animate-pulse rounded-full bg-muted" />
        <div className="h-7 w-40 animate-pulse rounded-full bg-muted" />
      </div>
    )
  }
  if (!hasSuggestions) return null

  return (
    <div className="flex flex-wrap gap-2 border-t border-border px-6 py-3">
      {data.suggestions.map((s) => (
        <button
          key={s.id || s.text}
          onClick={() => {
            if (s.id) {
              fetch(`${API_BASE}/chat/suggestions/${s.id}/asked`, { method: "POST" }).catch(() => { })
            }
            onSuggest(s.text)
          }}
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
  const res = await fetch(`${API_BASE}/documents?sort=last_accessed&page=1&page_size=100`)
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


interface WebSearchSettings {
  provider: string
  enabled: boolean
}

// S158: retrieval transparency metadata emitted by backend as 'transparency' SSE event
interface TransparencyInfo {
  confidence_level: string  // 'high' | 'medium' | 'low'
  strategy_used: string     // 'executive_summary' | 'hybrid_retrieval' | 'graph_traversal' | 'comparative' | 'augmented_hybrid'
  chunk_count: number
  section_count: number
  augmented: boolean
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
  type?: "text" | "card" | "divider"
  cardData?: AnyCardData
  citations?: Citation[]
  confidence?: Confidence
  not_found?: boolean
  isStreaming?: boolean
  image_ids?: string[]
  web_sources?: WebSource[]  // S142: web augmentation sources
  source_citations?: SourceCitation[]  // S148: chunk-derived deep-link citations
  transparency?: TransparencyInfo       // S158: retrieval transparency panel
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

// S158: transparency badge uses green/yellow/red per AC (not the shadcn Badge variant system)
const TRANSPARENCY_BADGE_CLASS: Record<string, string> = {
  high: "bg-green-100 text-green-800 border border-green-200",
  medium: "bg-yellow-100 text-yellow-800 border border-yellow-200",
  low: "bg-red-100 text-red-800 border border-red-200",
}

const STRATEGY_LABEL: Record<string, string> = {
  executive_summary: "Executive summary",
  hybrid_retrieval: "Hybrid retrieval (vector + keyword)",
  graph_traversal: "Graph traversal",
  comparative: "Comparative search",
  augmented_hybrid: "Augmented hybrid retrieval",
}

// S158: per-message transparency panel with collapsible "How I Answered" section
function TransparencyPanel({ transparency }: { transparency: TransparencyInfo }) {
  const [open, setOpen] = useState(TRANSPARENCY_DEFAULT_OPEN)
  const badgeClass =
    TRANSPARENCY_BADGE_CLASS[transparency.confidence_level] ??
    TRANSPARENCY_BADGE_CLASS["low"]

  return (
    <div className="mt-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${badgeClass}`}
        >
          {transparency.confidence_level} confidence
        </span>
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-muted-foreground hover:text-foreground transition-colors"
          aria-expanded={open}
          title={open ? "Hide retrieval details" : "How I answered"}
        >
          <Info size={13} />
        </button>
      </div>
      {open && (
        <div className="mt-2 rounded-md border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground space-y-1">
          <div>
            <span className="font-medium text-foreground">Strategy:</span>{" "}
            {STRATEGY_LABEL[transparency.strategy_used] ?? transparency.strategy_used}
          </div>
          <div>
            <span className="font-medium text-foreground">Sources:</span>{" "}
            {transparency.chunk_count} chunk{transparency.chunk_count !== 1 ? "s" : ""}
            {transparency.section_count > 0 ? ` from ${transparency.section_count} section${transparency.section_count !== 1 ? "s" : ""}` : ""}
          </div>
          {transparency.augmented && (
            <div className="italic">Context was extended after initial low confidence</div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// DocumentScopeCombobox -- inline document scope selector in Chat header (S186)
// ---------------------------------------------------------------------------

interface DocumentScopeComboboxProps {
  docList: DocListItem[] | undefined
  selectedDocId: string | null
  onSelect: (docId: string | null) => void
}

function DocumentScopeCombobox({ docList, selectedDocId, onSelect }: DocumentScopeComboboxProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const containerRef = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [open])

  const selectedTitle = docList?.find((d) => d.id === selectedDocId)?.title ?? null
  const label = buildScopeComboboxLabel(selectedTitle)

  const filtered = (docList ?? []).filter((d) =>
    d.title.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={() => { setOpen((prev) => !prev); setSearch("") }}
        className="flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground hover:bg-accent transition-colors max-w-[240px]"
        title={selectedTitle ?? "All documents"}
      >
        {selectedDocId ? (
          <>
            <BookOpen size={13} className="shrink-0 text-muted-foreground" />
            <span className="truncate">{label}</span>
            <button
              onClick={(e) => { e.stopPropagation(); onSelect(null) }}
              className="ml-0.5 shrink-0 rounded p-0.5 hover:bg-accent"
              aria-label="Clear document selection"
            >
              <X size={12} />
            </button>
          </>
        ) : (
          <>
            <Globe size={13} className="shrink-0 text-muted-foreground" />
            <span>{label}</span>
            <ChevronDown size={12} className="shrink-0 text-muted-foreground" />
          </>
        )}
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-64 rounded-md border border-border bg-background shadow-lg">
          <div className="border-b border-border px-2 py-1.5">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search documents..."
              className="w-full bg-transparent text-xs text-foreground placeholder:text-muted-foreground outline-none"
              autoFocus
            />
          </div>
          <div className="max-h-48 overflow-auto py-1">
            {docList === undefined ? (
              <div className="px-3 py-2">
                <Skeleton className="h-4 w-full" />
              </div>
            ) : filtered.length === 0 ? (
              <p className="px-3 py-2 text-xs text-muted-foreground">No documents yet</p>
            ) : (
              filtered.map((doc) => (
                <button
                  key={doc.id}
                  onClick={() => { onSelect(doc.id); setOpen(false) }}
                  className={`w-full px-3 py-1.5 text-left text-xs hover:bg-accent transition-colors truncate ${doc.id === selectedDocId ? "bg-accent/50 font-medium" : "text-foreground"
                    }`}
                >
                  {doc.title}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default function Chat() {
  const activeDocumentId = useAppStore((s) => s.activeDocumentId)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const chatPreload = useAppStore((s) => s.chatPreload)
  const clearChatPreload = useAppStore((s) => s.clearChatPreload)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const qc = useQueryClient()
  const messages = useAppStore((s) => s.chatMessages) as ChatMessage[]
  const setMessagesRaw = useAppStore((s) => s.setChatMessages)
  const setMessages = (updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => {
    if (typeof updater === "function") {
      setMessagesRaw(updater(useAppStore.getState().chatMessages as ChatMessage[]))
    } else {
      setMessagesRaw(updater)
    }
  }
  const [input, setInput] = useState("")
  const scope = useAppStore((s) => s.chatScope)
  const setScope = useAppStore((s) => s.setChatScope)
  // selectedDocId: explicit in-tab selection; falls back to global activeDocumentId
  const selectedDocId = useAppStore((s) => s.chatSelectedDocId)
  const setSelectedDocId = useAppStore((s) => s.setChatSelectedDocId)
  const [model, setModel] = useState<string>("")
  const [isStreaming, setIsStreaming] = useState(false)
  const qaError = useAppStore((s) => s.chatQaError)
  const setQaError = useAppStore((s) => s.setChatQaError)
  const [webEnabled, setWebEnabled] = useState(false)
  const [webCallsUsed, setWebCallsUsed] = useState(0)
  const [showPlanPanel, setShowPlanPanel] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
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
    if (activeDocumentId && !selectedDocId) {
      setSelectedDocId(activeDocumentId)
    }
  }, [activeDocumentId, selectedDocId]) // eslint-disable-line react-hooks/exhaustive-deps

  // S147: Pre-fill input from chatPreload set by SelectionActionBar "Ask in Chat" action
  // S197: autoSubmit flag triggers immediate send
  useEffect(() => {
    if (chatPreload) {
      const shouldAutoSubmit = chatPreload.autoSubmit
      setInput(chatPreload.text)
      if (chatPreload.documentId) {
        setSelectedDocId(chatPreload.documentId)
        setScope("single")
      }
      clearChatPreload()
      if (shouldAutoSubmit) {
        // Defer send to next tick so state updates (scope, docId) are applied
        setTimeout(() => void sendMessage(chatPreload.text), 100)
      } else {
        setTimeout(() => {
          textareaRef.current?.focus()
          autoResize()
        }, 50)
      }
    }
  }, [chatPreload, clearChatPreload]) // eslint-disable-line react-hooks/exhaustive-deps

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

            // S158: transparency event arrives before 'done' — silently omit if malformed
            if (payload["type"] === "transparency") {
              try {
                const raw = payload as Record<string, unknown>
                const transparency: TransparencyInfo = {
                  confidence_level: raw["confidence_level"] as string,
                  strategy_used: raw["strategy_used"] as string,
                  chunk_count: raw["chunk_count"] as number,
                  section_count: raw["section_count"] as number,
                  augmented: raw["augmented"] as boolean,
                }
                setMessages((m) =>
                  m.map((msg) =>
                    msg.id === assistantId ? { ...msg, transparency } : msg,
                  ),
                )
              } catch {
                // malformed transparency event — silent omission per AC
              }
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
              // S195: refresh suggestion pills after each answered question
              const suggestDocId = scope === "single" ? (selectedDocId ?? activeDocumentId) : null
              void qc.invalidateQueries({ queryKey: ["chat-suggestions", suggestDocId] })
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
    if (c.chunk_id) params.set("chunk_id", c.chunk_id)
    if (c.pdf_page_number) params.set("page", String(c.pdf_page_number))
    navigate(`/?${params.toString()}`)
  }

  const effectiveDocId = selectedDocId ?? activeDocumentId
  const noDocumentSelected = scope === "single" && !effectiveDocId

  return (
    <div className="flex h-full flex-col">
      {/* Header controls */}
      <div className="flex items-center gap-4 border-b border-border px-6 py-3">
        {/* S186: Inline document scope combobox */}
        <DocumentScopeCombobox
          docList={docList}
          selectedDocId={selectedDocId}
          onSelect={(docId) => {
            if (docId === null) {
              // S196: Clear -> revert to "All documents" -- preserve conversation
              if (scope === "single") {
                setScope("all")
                setSelectedDocId(null)
                if (messages.length > 0) {
                  setMessages((prev) => [
                    ...prev,
                    {
                      id: `divider-${Date.now()}`,
                      role: "assistant" as const,
                      text: "Switched to All documents",
                      type: "divider" as const,
                    },
                  ])
                }
              }
            } else if (selectedDocId === null || scope === "all") {
              // S196: Transition: all -> single -- insert divider, preserve conversation
              const docTitle = docList?.find((d) => d.id === docId)?.title ?? "Unknown"
              setScope("single")
              setSelectedDocId(docId)
              if (messages.length > 0) {
                setMessages((prev) => [
                  ...prev,
                  {
                    id: `divider-${Date.now()}`,
                    role: "assistant" as const,
                    text: `Scope changed to ${docTitle}`,
                    type: "divider" as const,
                  },
                ])
              }
            } else if (docId !== selectedDocId) {
              // Transition: single -> single (different doc) -- insert divider, do NOT clear
              const docTitle = docList?.find((d) => d.id === docId)?.title ?? "Unknown"
              setSelectedDocId(docId)
              setMessages((prev) => [
                ...prev,
                {
                  id: `divider-${Date.now()}`,
                  role: "assistant",
                  text: `Scope changed to ${docTitle}`,
                  type: "divider" as const,
                },
              ])
            }
            // docId === selectedDocId -> no-op
          }}
        />

        {/* Web call counter -- shown when web is enabled and conversation is active */}
        {webEnabled && messages.length > 0 && (
          <span className="text-xs text-muted-foreground">Web: {webCallsUsed}/3</span>
        )}

        {/* Clear conversation button -- only shown when there are messages */}
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

        {/* Settings gear icon -- opens ChatSettingsDrawer */}
        <button
          onClick={() => setSettingsOpen(true)}
          className={`${messages.length > 0 && !isStreaming ? "" : "ml-auto"} rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors`}
          title="Chat settings"
        >
          <Settings size={15} />
        </button>
      </div>

      {/* Chat settings drawer -- model selector, web toggle */}
      <ChatSettingsDrawer
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        model={model}
        onModelChange={setModel}
        modelOptions={modelOptions}
        llmLoading={llmLoading}
        webEnabled={webEnabled}
        onWebToggle={() => setWebEnabled((prev) => !prev)}
        webSearchSettings={webSearchSettings}
      />

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
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {messages.map((msg) => (
              msg.type === "divider" ? (
                <div key={msg.id} className="flex items-center gap-3 py-1">
                  <div className="h-px flex-1 bg-border" />
                  <span className="text-xs text-muted-foreground">{msg.text}</span>
                  <div className="h-px flex-1 bg-border" />
                </div>
              ) : (
                <div
                  key={msg.id}
                  className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[80%] rounded-lg px-4 py-3 ${msg.role === "user"
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

                    {/* Retrieval transparency panel: confidence badge + How I Answered (S158) */}
                    {!msg.isStreaming && msg.transparency && (
                      <TransparencyPanel transparency={msg.transparency} />
                    )}

                    {/* Source citation chips — deep-links to exact section/page (S157) */}
                    {!msg.isStreaming && (
                      <SourceCitationChips
                        citations={msg.source_citations ?? []}
                        navigateToCitation={navigateToCitation}
                      />
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
                              ; (e.currentTarget as HTMLImageElement).style.display = "none"
                            }}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Contextual suggestion pills — driven by GET /chat/suggestions (S187) */}
      {/* S196: Also show pills after a scope-change divider (last msg is divider) */}
      {(messages.length === 0 || messages[messages.length - 1]?.type === "divider") &&
        scope === "single" &&
        effectiveDocId && (
          <SuggestionPills
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
