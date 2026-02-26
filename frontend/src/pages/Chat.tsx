import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Send, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { logger } from "@/lib/logger"
import { useAppStore } from "@/store"

const API_BASE = "http://localhost:8000"

interface Citation {
  document_title: string
  section_heading: string
  page: number
  excerpt: string
}

type Confidence = "high" | "medium" | "low"

interface ChatMessage {
  id: string
  role: "user" | "assistant"
  text: string
  citations?: Citation[]
  confidence?: Confidence
  not_found?: boolean
  isStreaming?: boolean
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

function buildModelOptions(settings: LLMSettings | undefined): string[] {
  if (!settings) return []
  const opts: string[] = []
  for (const m of settings.available_local_models) opts.push(m)
  for (const p of settings.cloud_providers) {
    if (p.available) opts.push(p.name)
  }
  return opts.length > 0 ? opts : [settings.active_model]
}

export default function Chat() {
  const activeDocumentId = useAppStore((s) => s.activeDocumentId)
  const qc = useQueryClient()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [scope, setScope] = useState<"single" | "all">("all")
  const [model, setModel] = useState<string>("")
  const [isStreaming, setIsStreaming] = useState(false)
  const [qaError, setQaError] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const mountTime = useRef(Date.now())

  const { data: llmSettings, isLoading: llmLoading, isError: llmError } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: fetchLLMSettings,
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
      const documentIds = scope === "single" && activeDocumentId ? [activeDocumentId] : null
      const res = await fetch(`${API_BASE}/qa`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, document_ids: documentIds, scope, model: model || null }),
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
              const errorMsg =
                errorCode === "llm_unavailable"
                  ? "Ollama is not running. Start it with: ollama serve"
                  : (payload["message"] as string | undefined) ?? "An error occurred."
              setIsStreaming(false)
              setMessages((m) => m.filter((msg) => msg.id !== assistantId))
              setQaError(errorMsg)
              break
            }

            if (payload["done"] === true) {
              const not_found = payload["not_found"] === true
              const citations = (payload["citations"] as Citation[] | undefined) ?? []
              const confidence = (payload["confidence"] as Confidence | undefined) ?? "low"
              setMessages((m) =>
                m.map((msg) =>
                  msg.id === assistantId
                    ? { ...msg, isStreaming: false, citations, confidence, not_found }
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
      setQaError("Could not get a response. Please try again.")
      setMessages((m) =>
        m.filter((msg) => msg.id !== assistantId),
      )
      setIsStreaming(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      void sendMessage(input)
    }
  }

  const noDocumentSelected = scope === "single" && !activeDocumentId

  return (
    <div className="flex h-full flex-col">
      {/* Header controls */}
      <div className="flex items-center gap-4 border-b border-border px-6 py-3">
        {/* Scope selector */}
        <div className="flex items-center rounded-md border border-border">
          <button
            onClick={() => setScope("single")}
            className={`rounded-l-md px-3 py-1.5 text-xs font-medium transition-colors ${scope === "single" ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/50"}`}
          >
            This document
          </button>
          <button
            onClick={() => setScope("all")}
            className={`rounded-r-md px-3 py-1.5 text-xs font-medium transition-colors ${scope === "all" ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/50"}`}
          >
            All my content
          </button>
        </div>

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
                  {msg.not_found ? (
                    <p className="text-sm text-blue-600">
                      This information was not found in the selected content.
                    </p>
                  ) : (
                    <p className="whitespace-pre-wrap text-sm">
                      {msg.text}
                      {msg.isStreaming && <span className="animate-pulse">▍</span>}
                    </p>
                  )}

                  {/* Citations and confidence — shown after streaming completes */}
                  {!msg.isStreaming && msg.citations && msg.citations.length > 0 && (
                    <div className="mt-3 space-y-2">
                      <div className="flex flex-wrap gap-1.5">
                        {msg.citations.map((c, i) => (
                          <span
                            key={i}
                            className="rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                            title={c.excerpt}
                          >
                            {c.document_title} › {c.section_heading} (p.{c.page})
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
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
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
