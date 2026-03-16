/**
 * FeynmanDialog -- split-pane guided explanation session (S144).
 *
 * Left pane (40%): section summary (or fallback preview)
 * Right pane (60%): SSE-streaming Socratic tutor chat
 *
 * Three UI states:
 *   Loading: skeleton rows in left pane while summary loads
 *   Error: inline message when summary fetch fails or Ollama is offline
 *   Empty: "No session history" in history tab
 */

import { useEffect, useRef, useState } from "react"
import { Brain, Loader2, Send } from "lucide-react"
import { cn } from "@/lib/utils"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"

import { API_BASE } from "@/lib/config"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChatMessage {
  role: "tutor" | "learner"
  content: string
  gaps?: string[]
}

interface SessionHistoryItem {
  id: string
  concept: string
  status: string
  gap_count: number
  created_at: string
}

interface FeynmanDialogProps {
  documentId: string
  sectionId: string
  concept: string
  onClose: () => void
}

type DialogTab = "chat" | "history"

// ---------------------------------------------------------------------------
// FeynmanDialog
// ---------------------------------------------------------------------------

export function FeynmanDialog({
  documentId,
  sectionId,
  concept,
  onClose,
}: FeynmanDialogProps) {
  const [activeTab, setActiveTab] = useState<DialogTab>("chat")

  // Summary loading state
  const [summaryContent, setSummaryContent] = useState<string | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [summaryError, setSummaryError] = useState<string | null>(null)

  // Session state
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessionLoading, setSessionLoading] = useState(true)
  const [sessionError, setSessionError] = useState<string | null>(null)

  // Chat input
  const [inputText, setInputText] = useState("")
  const [sending, setSending] = useState(false)

  // Complete session state
  const [completing, setCompleting] = useState(false)
  const [completeResult, setCompleteResult] = useState<{ gap_count: number; flashcard_ids: string[] } | null>(null)

  // Session history
  const [history, setHistory] = useState<SessionHistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // ---------------------------------------------------------------------------
  // Load section summary (left pane)
  // ---------------------------------------------------------------------------

  useEffect(() => {
    let cancelled = false
    async function loadSummary() {
      setSummaryLoading(true)
      setSummaryError(null)
      try {
        // Try cached section summary first
        const res = await fetch(`${API_BASE}/summarize/${documentId}/cached`)
        if (!res.ok || cancelled) throw new Error("No cached summary")
        const data = (await res.json()) as {
          summaries: Record<string, { id: string; content: string }>
        }
        if (cancelled) return
        // Use executive mode if available
        if (data.summaries["executive"]) {
          setSummaryContent(data.summaries["executive"].content)
          return
        }
      } catch {
        // fall through to section preview
      }

      // Fallback: fetch section preview via document sections
      try {
        const res2 = await fetch(`${API_BASE}/documents/${documentId}`)
        if (!res2.ok || cancelled) throw new Error("Could not fetch document")
        const doc = (await res2.json()) as { sections: Array<{ id: string; preview: string; heading: string }> }
        const section = doc.sections.find((s) => s.id === sectionId)
        if (cancelled) return
        if (section?.preview) {
          setSummaryContent(section.preview)
          return
        }
      } catch {
        // ignore
      }

      if (!cancelled) {
        setSummaryContent(null)
        setSummaryError("No summary available for this section.")
      }
    }
    void loadSummary()
    return () => { cancelled = true }
  }, [documentId, sectionId])

  useEffect(() => {
    if (summaryContent !== null || summaryError !== null) setSummaryLoading(false)
  }, [summaryContent, summaryError])

  // ---------------------------------------------------------------------------
  // Create session on mount
  // ---------------------------------------------------------------------------

  useEffect(() => {
    let cancelled = false
    async function startSession() {
      setSessionLoading(true)
      setSessionError(null)
      try {
        const res = await fetch(`${API_BASE}/feynman/sessions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            document_id: documentId,
            section_id: sectionId,
            concept,
          }),
        })
        if (cancelled) return
        if (!res.ok) {
          if (res.status === 503) {
            setSessionError("Ollama is not running. Start it with: ollama serve")
          } else {
            setSessionError(`Failed to start session (HTTP ${res.status})`)
          }
          setSessionLoading(false)
          return
        }
        const data = (await res.json()) as {
          id: string
          opening_message: string
        }
        if (cancelled) return
        setSessionId(data.id)
        setMessages([{ role: "tutor", content: data.opening_message }])
      } catch {
        if (!cancelled) {
          setSessionError("Ollama is not running. Start it with: ollama serve")
        }
      } finally {
        if (!cancelled) setSessionLoading(false)
      }
    }
    void startSession()
    return () => {
      cancelled = true
      abortRef.current?.abort()
    }
  }, [documentId, sectionId, concept])

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // ---------------------------------------------------------------------------
  // Load session history
  // ---------------------------------------------------------------------------

  function loadHistory() {
    setHistoryLoading(true)
    setHistoryError(null)
    fetch(`${API_BASE}/feynman/sessions?document_id=${encodeURIComponent(documentId)}`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch session history")
        return res.json() as Promise<SessionHistoryItem[]>
      })
      .then((data) => {
        setHistory(data)
        setHistoryLoading(false)
      })
      .catch(() => {
        setHistoryError("Could not load session history.")
        setHistoryLoading(false)
      })
  }

  useEffect(() => {
    if (activeTab === "history") loadHistory()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab])

  // ---------------------------------------------------------------------------
  // Send message
  // ---------------------------------------------------------------------------

  async function handleSend() {
    if (!sessionId || !inputText.trim() || sending) return
    const userText = inputText.trim()
    setInputText("")
    setSending(true)

    setMessages((prev) => [...prev, { role: "learner", content: userText }])

    const controller = new AbortController()
    abortRef.current = controller

    // Add empty tutor message placeholder
    setMessages((prev) => [...prev, { role: "tutor", content: "" }])

    try {
      const res = await fetch(`${API_BASE}/feynman/sessions/${sessionId}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: userText }),
        signal: controller.signal,
      })

      if (!res.ok || !res.body) {
        setMessages((prev) => [
          ...prev.slice(0, -1),
          { role: "tutor", content: "Error: Could not get response." },
        ])
        setSending(false)
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      let accumulatedText = ""

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
              accumulatedText += payload["token"]
              setMessages((prev) => [
                ...prev.slice(0, -1),
                { role: "tutor", content: accumulatedText },
              ])
            }
            if (payload["error"] === "llm_unavailable") {
              const msg = typeof payload["message"] === "string"
                ? payload["message"]
                : "Ollama is not running. Start it with: ollama serve"
              setMessages((prev) => [
                ...prev.slice(0, -1),
                { role: "tutor", content: msg },
              ])
            }
            if (payload["done"] === true) {
              const finalText = typeof payload["answer"] === "string"
                ? payload["answer"]
                : accumulatedText
              const gaps = Array.isArray(payload["gaps"])
                ? (payload["gaps"] as string[])
                : []
              setMessages((prev) => [
                ...prev.slice(0, -1),
                { role: "tutor", content: finalText, gaps },
              ])
            }
          } catch {
            // skip malformed SSE
          }
        }
      }
    } catch (err) {
      if ((err as { name?: string }).name !== "AbortError") {
        setMessages((prev) => [
          ...prev.slice(0, -1),
          { role: "tutor", content: "Error: Connection failed. Check that Ollama is running." },
        ])
      }
    } finally {
      setSending(false)
      abortRef.current = null
    }
  }

  // ---------------------------------------------------------------------------
  // Complete session
  // ---------------------------------------------------------------------------

  async function handleComplete() {
    if (!sessionId || completing) return
    setCompleting(true)
    try {
      const res = await fetch(`${API_BASE}/feynman/sessions/${sessionId}/complete`, {
        method: "POST",
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = (await res.json()) as { gap_count: number; flashcard_ids: string[] }
      setCompleteResult(data)
    } catch {
      setSessionError("Could not complete session. Please try again.")
    } finally {
      setCompleting(false)
    }
  }

  const learnerTurnCount = messages.filter((m) => m.role === "learner").length

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="flex max-w-5xl flex-col gap-0 p-0 h-[80vh]">
        <DialogHeader className="border-b border-border px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Brain size={16} className="text-primary" />
              <DialogTitle className="text-base font-semibold">
                Feynman Mode: {concept}
              </DialogTitle>
            </div>
            {/* Tab bar */}
            <div className="flex gap-1 rounded-md bg-muted p-0.5 text-xs">
              {(["chat", "history"] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={cn(
                    "rounded px-3 py-1 font-medium capitalize transition-colors",
                    activeTab === tab
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {tab}
                </button>
              ))}
            </div>
          </div>
        </DialogHeader>

        {activeTab === "chat" ? (
          <div className="flex flex-1 overflow-hidden">
            {/* Left pane: section summary */}
            <div className="w-2/5 overflow-auto border-r border-border p-4">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Section Reference
              </h3>
              {summaryLoading ? (
                <div className="flex flex-col gap-2">
                  {[1, 2, 3, 4, 5].map((i) => (
                    <Skeleton key={i} className="h-3 w-full" />
                  ))}
                </div>
              ) : summaryError ? (
                <p className="text-xs text-muted-foreground">{summaryError}</p>
              ) : summaryContent ? (
                <div className="text-xs leading-relaxed">
                  <MarkdownRenderer>{summaryContent}</MarkdownRenderer>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">No summary available for this section.</p>
              )}
            </div>

            {/* Right pane: chat */}
            <div className="flex w-3/5 flex-col overflow-hidden">
              {/* Error banner */}
              {sessionError && (
                <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800">
                  {sessionError}
                </div>
              )}

              {/* Messages area */}
              <div className="flex-1 overflow-auto p-4">
                {sessionLoading ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 size={14} className="animate-spin" />
                    Starting session...
                  </div>
                ) : messages.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Starting your session...</p>
                ) : (
                  <div className="flex flex-col gap-3">
                    {messages.map((msg, i) => (
                      <div
                        key={i}
                        className={cn(
                          "max-w-[90%] rounded-lg px-3 py-2 text-sm",
                          msg.role === "tutor"
                            ? "self-start bg-muted text-foreground"
                            : "self-end bg-primary text-primary-foreground",
                        )}
                      >
                        <p className="whitespace-pre-wrap">{msg.content}</p>
                        {msg.gaps && msg.gaps.length > 0 && (
                          <div className="mt-1.5 border-t border-current/20 pt-1">
                            <p className="text-xs opacity-70">
                              Gaps identified: {msg.gaps.join(", ")}
                            </p>
                          </div>
                        )}
                      </div>
                    ))}
                    <div ref={messagesEndRef} />
                  </div>
                )}
              </div>

              {/* Complete session banner */}
              {completeResult !== null ? (
                <div className="border-t border-border px-4 py-3 text-center">
                  <p className="text-sm font-medium text-foreground">
                    Session complete!{" "}
                    {completeResult.gap_count > 0
                      ? `${completeResult.flashcard_ids.length} flashcard${completeResult.flashcard_ids.length !== 1 ? "s" : ""} created from ${completeResult.gap_count} gap${completeResult.gap_count !== 1 ? "s" : ""}.`
                      : "No gaps identified -- great job!"}
                  </p>
                  <button
                    onClick={onClose}
                    className="mt-2 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
                  >
                    Done
                  </button>
                </div>
              ) : (
                <>
                  {/* Complete button (shown after >= 2 learner turns) */}
                  {learnerTurnCount >= 2 && !completeResult && (
                    <div className="border-t border-border px-4 py-2">
                      <button
                        onClick={() => void handleComplete()}
                        disabled={completing || sending}
                        className="w-full rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 disabled:opacity-50"
                      >
                        {completing ? (
                          <span className="flex items-center justify-center gap-1">
                            <Loader2 size={11} className="animate-spin" />
                            Generating flashcards...
                          </span>
                        ) : (
                          "Complete session and generate flashcards"
                        )}
                      </button>
                    </div>
                  )}

                  {/* Chat input */}
                  <div className="border-t border-border p-3">
                    <div className="flex gap-2">
                      <textarea
                        value={inputText}
                        onChange={(e) => setInputText(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey) {
                            e.preventDefault()
                            void handleSend()
                          }
                        }}
                        placeholder="Type your explanation... (Enter to send, Shift+Enter for newline)"
                        disabled={sending || sessionLoading || !!sessionError}
                        rows={3}
                        className="flex-1 resize-none rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
                      />
                      <button
                        onClick={() => void handleSend()}
                        disabled={sending || !inputText.trim() || sessionLoading || !!sessionError}
                        className="self-end rounded-md bg-primary p-2 text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                        aria-label="Send message"
                      >
                        {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        ) : (
          /* History tab */
          <div className="flex-1 overflow-auto p-6">
            <h3 className="mb-3 text-sm font-semibold text-foreground">Session History</h3>
            {historyLoading ? (
              <div className="flex flex-col gap-2">
                {[1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
              </div>
            ) : historyError ? (
              <p className="text-sm text-destructive">{historyError}</p>
            ) : history.length === 0 ? (
              <p className="text-sm text-muted-foreground">No session history for this document.</p>
            ) : (
              <div className="flex flex-col gap-2">
                {history.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-center justify-between rounded-md border border-border p-3"
                  >
                    <div>
                      <p className="text-sm font-medium text-foreground">{item.concept}</p>
                      <p className="text-xs text-muted-foreground">
                        {item.gap_count > 0
                          ? `${item.gap_count} gap${item.gap_count !== 1 ? "s" : ""} identified`
                          : "No gaps identified"}
                        {" · "}
                        {new Date(item.created_at).toLocaleDateString()}
                      </p>
                    </div>
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-xs font-medium",
                        item.status === "complete"
                          ? "bg-green-100 text-green-700"
                          : "bg-amber-100 text-amber-700",
                      )}
                    >
                      {item.status}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
