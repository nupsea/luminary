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
import { RubricCard, type Rubric } from "@/components/RubricCard"
import { computeExplanationDiff, splitSentences, type DiffSegment } from "@/lib/explanationDiff"

import { ApiError, apiGet, apiPost } from "@/lib/apiClient"
import { API_BASE } from "@/lib/config"
import {
  fetchSummary,
  summaryCache,
  summaryCacheKey,
  summaryInflight,
} from "./feynmanSummaryCache"

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
  const [completeResult, setCompleteResult] = useState<{ gap_count: number; flashcard_ids: string[]; rubric: Rubric | null } | null>(null)

  // Session history
  const [history, setHistory] = useState<SessionHistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)

  // S159: model explanation state
  const [showModelExplanation, setShowModelExplanation] = useState(false)
  const [modelExplanationStreaming, setModelExplanationStreaming] = useState(false)
  const [modelExplanationText, setModelExplanationText] = useState<string | null>(null)
  const [modelKeyPoints, setModelKeyPoints] = useState<string[]>([])
  const [modelExplanationError, setModelExplanationError] = useState<string | null>(null)
  const [diffSegments, setDiffSegments] = useState<DiffSegment[]>([])
  const [savingNote, setSavingNote] = useState(false)
  const [noteSaved, setNoteSaved] = useState(false)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // ---------------------------------------------------------------------------
  // Load section summary (left pane)
  // ---------------------------------------------------------------------------

  useEffect(() => {
    let cancelled = false
    const key = summaryCacheKey(documentId, sectionId)

    // Cache hit: render summary synchronously, no skeleton flash.
    const cached = summaryCache.get(key)
    if (cached !== undefined) {
      setSummaryContent(cached)
      setSummaryLoading(false)
      setSummaryError(null)
      return
    }

    setSummaryLoading(true)
    setSummaryError(null)

    // Reuse an in-flight prefetch if one was started on hover/focus.
    const inflight = summaryInflight.get(key) ?? (() => {
      const p = fetchSummary(documentId, sectionId).then((content) => {
        summaryInflight.delete(key)
        if (content !== null) summaryCache.set(key, content)
        return content
      })
      summaryInflight.set(key, p)
      return p
    })()

    void inflight.then((content) => {
      if (cancelled) return
      if (content !== null) {
        setSummaryContent(content)
      } else {
        setSummaryContent(null)
        setSummaryError("No summary available for this section.")
      }
    })

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
        const data = await apiPost<{ id: string; opening_message: string }>(
          "/feynman/sessions",
          { document_id: documentId, section_id: sectionId, concept },
        )
        if (cancelled) return
        setSessionId(data.id)
        setMessages([{ role: "tutor", content: data.opening_message }])
      } catch (err) {
        if (cancelled) return
        if (err instanceof ApiError && err.status !== 503) {
          setSessionError(`Failed to start session (HTTP ${err.status})`)
        } else {
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
    apiGet<SessionHistoryItem[]>("/feynman/sessions", {
      document_id: documentId,
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
      // SSE stream: tokens arrive via res.body.getReader(); apiClient's
      // JSON path doesn't apply.
      // eslint-disable-next-line no-restricted-syntax
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
      const data = await apiPost<{
        gap_count: number
        flashcard_ids: string[]
        rubric: Rubric | null
      }>(`/feynman/sessions/${sessionId}/complete`)
      setCompleteResult({
        gap_count: data.gap_count,
        flashcard_ids: data.flashcard_ids,
        rubric: data.rubric ?? null,
      })
    } catch {
      setSessionError("Could not complete session. Please try again.")
    } finally {
      setCompleting(false)
    }
  }

  const learnerTurnCount = messages.filter((m) => m.role === "learner").length

  // ---------------------------------------------------------------------------
  // S159: Model explanation fetch and diff computation
  // ---------------------------------------------------------------------------

  async function handleFetchModelExplanation() {
    if (!sessionId || modelExplanationStreaming) return
    setShowModelExplanation(true)
    setModelExplanationStreaming(true)
    setModelExplanationError(null)
    setModelExplanationText(null)
    setDiffSegments([])

    try {
      // SSE stream: tokens arrive via res.body.getReader(); apiClient's
      // JSON path doesn't apply.
      // eslint-disable-next-line no-restricted-syntax
      const res = await fetch(`${API_BASE}/feynman/sessions/${sessionId}/model-explanation`, {
        method: "POST",
      })
      if (!res.ok || !res.body) {
        setModelExplanationError(`Failed to load model explanation (HTTP ${res.status})`)
        setModelExplanationStreaming(false)
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      let streamedText = ""

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
              streamedText += payload["token"]
              setModelExplanationText(streamedText)
            }
            if (payload["error"] === "llm_unavailable" || payload["error"] === "not_found") {
              const msg = typeof payload["message"] === "string"
                ? payload["message"]
                : "Could not generate model explanation."
              setModelExplanationError(msg)
            }
            if (payload["done"] === true) {
              const finalText = typeof payload["explanation"] === "string"
                ? payload["explanation"]
                : streamedText
              const kp = Array.isArray(payload["key_points"])
                ? (payload["key_points"] as string[])
                : []
              setModelExplanationText(finalText)
              setModelKeyPoints(kp)

              // Compute diff against user explanation
              const userText = messages
                .filter((m) => m.role === "learner")
                .map((m) => m.content)
                .join(" ")
              const userSentences = splitSentences(userText)
              const modelSentences = splitSentences(finalText)
              setDiffSegments(computeExplanationDiff(userSentences, modelSentences))
            }
          } catch {
            // skip malformed SSE
          }
        }
      }
    } catch {
      setModelExplanationError("Connection failed. Check that Ollama is running.")
    } finally {
      setModelExplanationStreaming(false)
    }
  }

  async function handleSaveNote() {
    if (!modelExplanationText || savingNote || noteSaved) return
    setSavingNote(true)
    try {
      const noteContent = `## Model Explanation: ${concept}\n\n${modelExplanationText}${modelKeyPoints.length > 0 ? `\n\n**Key points:** ${modelKeyPoints.join(", ")}` : ""}\n\n_Generated by Luminary Feynman mode_`
      await apiPost("/notes", {
        document_id: documentId,
        section_id: sectionId,
        content: noteContent,
        tags: ["feynman", "model-explanation"],
      })
      setNoteSaved(true)
    } catch {
      setModelExplanationError("Could not save note. Please try again.")
    } finally {
      setSavingNote(false)
    }
  }

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
                <div className="border-t border-border px-4 py-3 overflow-auto max-h-[55vh]">
                  <p className="mb-2 text-sm font-medium text-foreground">Session complete!</p>
                  {completeResult.rubric ? (
                    <RubricCard rubric={completeResult.rubric} documentId={documentId} />
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      {completeResult.gap_count > 0
                        ? `${completeResult.flashcard_ids.length} flashcard${completeResult.flashcard_ids.length !== 1 ? "s" : ""} created from ${completeResult.gap_count} gap${completeResult.gap_count !== 1 ? "s" : ""}.`
                        : "No gaps identified -- great job!"}
                    </p>
                  )}

                  {/* S159: See model explanation button (only when concept + sectionId present) */}
                  {concept && sectionId && !showModelExplanation && (
                    <button
                      onClick={() => void handleFetchModelExplanation()}
                      className="mt-3 mr-2 rounded-md border border-primary px-4 py-1.5 text-xs font-medium text-primary hover:bg-primary/10"
                    >
                      See model explanation
                    </button>
                  )}

                  {/* S159: Model explanation panel */}
                  {showModelExplanation && (
                    <div className="mt-3 rounded-md border border-border p-3">
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Model Explanation
                      </p>
                      {modelExplanationError ? (
                        <p className="text-xs text-destructive">{modelExplanationError}</p>
                      ) : modelExplanationStreaming && !modelExplanationText ? (
                        <div className="flex flex-col gap-1.5">
                          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-3 w-full" />)}
                        </div>
                      ) : diffSegments.length > 0 ? (
                        <>
                          <div className="mb-2 flex gap-3 text-xs text-muted-foreground">
                            <span><span className="inline-block h-2 w-2 rounded-full bg-green-500 mr-1" />shared</span>
                            <span><span className="inline-block h-2 w-2 rounded-full bg-red-400 mr-1" />model only</span>
                            <span><span className="inline-block h-2 w-2 rounded-full bg-blue-400 mr-1" />you only</span>
                          </div>
                          <p className="text-xs leading-relaxed">
                            {diffSegments.map((seg, idx) => (
                              <span
                                key={idx}
                                className={cn(
                                  "rounded px-0.5",
                                  seg.kind === "shared" && "bg-green-100 text-green-900",
                                  seg.kind === "model_only" && "bg-red-100 text-red-900",
                                  seg.kind === "user_only" && "bg-blue-100 text-blue-900",
                                )}
                              >
                                {seg.text}.{" "}
                              </span>
                            ))}
                          </p>
                          {modelKeyPoints.length > 0 && (
                            <div className="mt-2">
                              <p className="text-xs font-medium text-muted-foreground">Key points:</p>
                              <ul className="mt-1 list-disc pl-4 text-xs text-foreground">
                                {modelKeyPoints.map((kp, i) => <li key={i}>{kp}</li>)}
                              </ul>
                            </div>
                          )}
                          <div className="mt-3 flex gap-2">
                            {!noteSaved ? (
                              <button
                                onClick={() => void handleSaveNote()}
                                disabled={savingNote}
                                className="rounded-md border border-border px-3 py-1 text-xs font-medium text-foreground hover:bg-muted disabled:opacity-50"
                              >
                                {savingNote ? "Saving..." : "Save as note"}
                              </button>
                            ) : (
                              <span className="text-xs text-green-700">Note saved</span>
                            )}
                          </div>
                        </>
                      ) : modelExplanationText ? (
                        <p className="text-xs leading-relaxed">{modelExplanationText}</p>
                      ) : null}
                    </div>
                  )}

                  <button
                    onClick={onClose}
                    className="mt-3 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
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
