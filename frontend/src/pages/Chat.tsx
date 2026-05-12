import { useQuery, useQueryClient } from "@tanstack/react-query"
import { PanelLeft, PanelLeftClose, Send, Settings, Trash2, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { toast } from "sonner"

import { ChatSessionList } from "@/components/chat/ChatSessionList"
import { ChatSettingsDrawer } from "@/components/ChatSettingsDrawer"
import type { SourceCitation } from "@/components/SourceCitationChips"
import { Skeleton } from "@/components/ui/skeleton"
import {
  appendChatMessage,
  createChatSession,
  deleteChatSession,
  getChatSession,
  renameChatSession,
} from "@/lib/chatSessionsApi"
import { buildModelOptions } from "@/lib/chatSettingsUtils"
import { logger } from "@/lib/logger"
import { useAppStore } from "@/store"

import {
  fetchDocList,
  fetchLLMSettings,
  fetchSessionPlan,
  fetchWebSearchSettings,
  persistedToChatMessage,
} from "./Chat/api"
import { DocumentScopeCombobox } from "./Chat/DocumentScopeCombobox"
import { MessageBubble } from "./Chat/MessageBubble"
import { buildErrorMessage, streamQa } from "./Chat/qaStream"
import { SessionPlanPanel } from "./Chat/SessionPlanPanel"
import { SuggestionPills } from "./Chat/SuggestionPills"
import type { ChatMessage } from "./Chat/types"

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
  const selectedDocId = useAppStore((s) => s.chatSelectedDocId)
  const setSelectedDocId = useAppStore((s) => s.setChatSelectedDocId)
  const [model, setModel] = useState<string>("")
  const [isStreaming, setIsStreaming] = useState(false)
  const qaError = useAppStore((s) => s.chatQaError)
  const setQaError = useAppStore((s) => s.setChatQaError)
  const activeSessionId = useAppStore((s) => s.activeChatSessionId)
  const setActiveSessionId = useAppStore((s) => s.setActiveChatSessionId)
  const sidebarOpen = useAppStore((s) => s.chatSidebarOpen)
  const setSidebarOpen = useAppStore((s) => s.setChatSidebarOpen)
  const [hydratingSession, setHydratingSession] = useState(false)
  const [webEnabled, setWebEnabled] = useState(false)
  const [webCallsUsed, setWebCallsUsed] = useState(0)
  const [showPlanPanel, setShowPlanPanel] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const mountTime = useRef(Date.now())

  const { data: docList } = useQuery({
    queryKey: ["chat-doc-list"],
    queryFn: fetchDocList,
    staleTime: 30_000,
  })

  // Pre-populate from global store when user arrives from Learning tab. Use a
  // ref so we don't re-populate after the user explicitly clears the selection.
  const docSelectorTouched = useRef(false)
  useEffect(() => {
    if (activeDocumentId && !selectedDocId && !docSelectorTouched.current) {
      setSelectedDocId(activeDocumentId)
      setScope("single")
    }
  }, [activeDocumentId, selectedDocId]) // eslint-disable-line react-hooks/exhaustive-deps

  // S147: Pre-fill input from chatPreload set by SelectionActionBar; S197: autoSubmit triggers send.
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
        setTimeout(() => void sendMessage(chatPreload.text), 100)
      } else {
        setTimeout(() => {
          textareaRef.current?.focus()
          autoResize()
        }, 50)
      }
    }
  }, [chatPreload, clearChatPreload]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const prefill = searchParams.get("q")
    if (prefill) setInput(prefill)
  }, [searchParams])

  const { data: llmSettings, isLoading: llmLoading, isError: llmError } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: fetchLLMSettings,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  })

  const { data: webSearchSettings } = useQuery({
    queryKey: ["web-search-settings"],
    queryFn: fetchWebSearchSettings,
    staleTime: 300_000,
    refetchOnWindowFocus: false,
  })

  const {
    data: sessionPlan,
    isLoading: planLoading,
    isError: planError,
    refetch: refetchPlan,
  } = useQuery({
    queryKey: ["session-plan"],
    queryFn: fetchSessionPlan,
    enabled: showPlanPanel,
    staleTime: 60_000,
  })

  const modelOptions = buildModelOptions(llmSettings)

  const cachedDocs = qc.getQueryData<{ items?: unknown[] } | unknown[]>(
    ["documents", undefined, null, "newest", 1, 20],
  )
  const hasDocuments = Array.isArray(cachedDocs)
    ? cachedDocs.length > 0
    : (cachedDocs as { items?: unknown[] } | undefined)?.items?.length !== 0

  useEffect(() => {
    logger.info("[Chat] mounted")
  }, [])

  // Hydrate from server explicitly. Used on initial mount and on sidebar click.
  // We deliberately do NOT auto-hydrate on every activeSessionId change, because
  // sendMessage and switchContextWithUndo also flip activeSessionId, and a
  // hydration race during streaming would clobber the in-flight assistant turn.
  async function hydrateSession(id: string) {
    setHydratingSession(true)
    try {
      const sess = await getChatSession(id)
      const hydrated: ChatMessage[] = sess.messages.map(persistedToChatMessage)
      setMessagesRaw(hydrated)
      setScope(sess.scope)
      setSelectedDocId(sess.document_ids[0] ?? null)
      setQaError(null)
    } catch {
      setActiveSessionId(null)
      setMessagesRaw([])
    } finally {
      setHydratingSession(false)
    }
  }

  const didInitialHydrate = useRef(false)
  useEffect(() => {
    if (didInitialHydrate.current) return
    didInitialHydrate.current = true
    const persistedId = useAppStore.getState().activeChatSessionId
    if (persistedId) void hydrateSession(persistedId)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function startNewChat() {
    setActiveSessionId(null)
    setMessagesRaw([])
    setQaError(null)
    setWebCallsUsed(0)
    docSelectorTouched.current = false
  }

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
    startNewChat()
  }

  async function switchContextWithUndo(nextScope: "single" | "all", nextDocId: string | null) {
    const prevSessionId = useAppStore.getState().activeChatSessionId
    const prevMessages = useAppStore.getState().chatMessages as ChatMessage[]
    const prevScope = scope
    const prevDocId = selectedDocId
    const labelDoc =
      nextScope === "single" && nextDocId
        ? (docList?.find((d) => d.id === nextDocId)?.title ?? "this document")
        : "All documents"

    if (prevMessages.length === 0 || !prevSessionId) {
      setScope(nextScope)
      setSelectedDocId(nextDocId)
      return
    }

    try {
      const created = await createChatSession({
        scope: nextScope,
        document_ids: nextScope === "single" && nextDocId ? [nextDocId] : [],
        model: model || null,
      })
      setActiveSessionId(created.id)
      setMessagesRaw([])
      setScope(nextScope)
      setSelectedDocId(nextDocId)
      void qc.invalidateQueries({ queryKey: ["chat-sessions"] })

      toast(`New chat for ${labelDoc}`, {
        action: {
          label: "Undo",
          onClick: () => {
            void deleteChatSession(created.id).catch(() => {})
            setActiveSessionId(prevSessionId)
            setMessagesRaw(prevMessages)
            setScope(prevScope)
            setSelectedDocId(prevDocId)
            void qc.invalidateQueries({ queryKey: ["chat-sessions"] })
          },
        },
        duration: 6000,
      })
    } catch (err) {
      logger.warn("[Chat] switchContextWithUndo failed", { err: String(err) })
      setScope(nextScope)
      setSelectedDocId(nextDocId)
    }
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

    // Resolve / create the persisted session before streaming, so the user turn
    // and the assistant turn share a stable id.
    const effectiveDocIdAtSend = selectedDocId ?? activeDocumentId
    const sessionDocIds =
      scope === "single" && effectiveDocIdAtSend ? [effectiveDocIdAtSend] : []
    let sessionId = useAppStore.getState().activeChatSessionId
    const isFirstTurn =
      !sessionId || (useAppStore.getState().chatMessages as ChatMessage[]).length === 0
    if (!sessionId) {
      try {
        const created = await createChatSession({
          scope,
          document_ids: sessionDocIds,
          model: model || null,
        })
        sessionId = created.id
        setActiveSessionId(created.id)
        void qc.invalidateQueries({ queryKey: ["chat-sessions"] })
      } catch (err) {
        logger.warn("[Chat] session create failed; falling back to ephemeral", { err: String(err) })
        sessionId = null
      }
    }

    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", text: question }
    const assistantId = crypto.randomUUID()
    const assistantMsg: ChatMessage = { id: assistantId, role: "assistant", text: "", isStreaming: true }
    setMessages((m) => [...m, userMsg, assistantMsg])
    setIsStreaming(true)

    if (sessionId) {
      void appendChatMessage(sessionId, { role: "user", content: question }).catch(() => {})
    }

    const effectiveDocId = selectedDocId ?? activeDocumentId
    const documentIds = scope === "single" && effectiveDocId ? [effectiveDocId] : null

    // Last 6 completed messages (3 exchanges) as conversation history.
    const historySlice = messages
      .filter((m) => !m.isStreaming && !m.not_found && m.text && m.type !== "divider")
      .slice(-6)
      .map((m) => ({ role: m.role, content: m.text }))

    try {
      await streamQa(
        {
          question,
          document_ids: documentIds,
          scope,
          model: model || null,
          messages: historySlice.length > 0 ? historySlice : undefined,
          web_enabled: webEnabled,
        },
        {
          onCard: (card) => {
            setMessages((m) =>
              m.map((msg) =>
                msg.id === assistantId
                  ? { ...msg, type: "card" as const, cardData: card, isStreaming: false, text: "" }
                  : msg,
              ),
            )
          },
          onToken: (token) => {
            setMessages((m) =>
              m.map((msg) => (msg.id === assistantId ? { ...msg, text: msg.text + token } : msg)),
            )
          },
          onTransparency: (transparency) => {
            setMessages((m) =>
              m.map((msg) => (msg.id === assistantId ? { ...msg, transparency } : msg)),
            )
          },
          onError: (errorCode, fallback) => {
            setIsStreaming(false)
            setMessages((m) => m.filter((msg) => msg.id !== assistantId))
            setQaError(buildErrorMessage(errorCode, fallback))
          },
          onDone: (done) => {
            setWebCallsUsed(done.web_calls_used ?? webCallsUsed)
            setMessages((m) =>
              m.map((msg) =>
                msg.id === assistantId
                  ? {
                      ...msg,
                      // Replace streamed tokens with the clean parsed answer
                      // from backend. This drops citation JSON fragments that
                      // leaked during streaming.
                      text: done.finalAnswer !== undefined ? done.finalAnswer : msg.text,
                      isStreaming: false,
                      citations: done.citations,
                      confidence: done.confidence,
                      not_found: done.not_found,
                      image_ids: done.image_ids,
                      web_sources: done.web_sources,
                      source_citations: done.source_citations,
                    }
                  : msg,
              ),
            )
            setIsStreaming(false)
            // S195: refresh suggestion pills after each answered question
            const suggestDocId = scope === "single" ? (selectedDocId ?? activeDocumentId) : null
            void qc.invalidateQueries({ queryKey: ["chat-suggestions", suggestDocId] })

            if (sessionId) {
              const finalText =
                done.finalAnswer !== undefined
                  ? done.finalAnswer
                  : (useAppStore.getState().chatMessages as ChatMessage[]).find(
                      (mm) => mm.id === assistantId,
                    )?.text ?? ""
              const transparencyAtDone = (useAppStore.getState().chatMessages as ChatMessage[]).find(
                (mm) => mm.id === assistantId,
              )?.transparency
              void appendChatMessage(sessionId, {
                role: "assistant",
                content: finalText,
                extra: {
                  citations: done.citations,
                  confidence: done.confidence,
                  image_ids: done.image_ids,
                  web_sources: done.web_sources,
                  source_citations: done.source_citations,
                  not_found: done.not_found,
                  transparency: transparencyAtDone,
                },
              })
                .then(() => qc.invalidateQueries({ queryKey: ["chat-sessions"] }))
                .catch(() => {})
              if (isFirstTurn) {
                void renameChatSession(sessionId, { auto_from_message: question })
                  .then(() => qc.invalidateQueries({ queryKey: ["chat-sessions"] }))
                  .catch(() => {})
              }
            }
          },
        },
      )
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err)
      logger.error("[Chat] fetch failed", { endpoint: "/qa", error: errMsg })
      setQaError(
        errMsg.includes("Failed to fetch") || errMsg.includes("NetworkError")
          ? "Cannot reach the server. Is the backend running on port 7820?"
          : `Could not get a response: ${errMsg}`,
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

  // S148: navigate to Learning tab with DocumentReader open at the cited section/page.
  function navigateToCitation(c: SourceCitation) {
    setActiveDocument(c.document_id)
    useAppStore.getState().setChatPanelOpen(false)
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
    <div className="flex h-full">
      {sidebarOpen && (
        <aside className="w-72 shrink-0 hidden md:flex md:flex-col">
          <ChatSessionList
            activeSessionId={activeSessionId}
            onSelect={(id) => {
              if (isStreaming) return
              setActiveSessionId(id)
              void hydrateSession(id)
            }}
            onNewChat={() => {
              if (isStreaming) return
              startNewChat()
            }}
          />
        </aside>
      )}
      <div className="flex h-full flex-col flex-1 min-w-0">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-border px-6 py-3">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
            title={sidebarOpen ? "Hide chat list" : "Show chat list"}
            aria-label={sidebarOpen ? "Hide chat list" : "Show chat list"}
          >
            {sidebarOpen ? <PanelLeftClose size={15} /> : <PanelLeft size={15} />}
          </button>
          {hydratingSession && (
            <span className="text-xs text-muted-foreground">Loading chat...</span>
          )}
          <DocumentScopeCombobox
            docList={docList}
            selectedDocId={selectedDocId}
            onSelect={(docId) => {
              docSelectorTouched.current = true
              // Mid-conversation context changes (scope or selected book) start
              // a new persisted chat. The user can undo from the toast.
              if (docId === null) {
                if (scope !== "all" || selectedDocId !== null) {
                  void switchContextWithUndo("all", null)
                }
              } else if (docId !== selectedDocId || scope === "all") {
                void switchContextWithUndo("single", docId)
              }
            }}
          />

          {webEnabled && messages.length > 0 && (
            <span className="text-xs text-muted-foreground">Web: {webCallsUsed}/3</span>
          )}

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

          <button
            onClick={() => setSettingsOpen(true)}
            className={`${messages.length > 0 && !isStreaming ? "" : "ml-auto"} rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors`}
            title="Chat settings"
          >
            <Settings size={15} />
          </button>
        </div>

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

        {llmError && (
          <div className="mx-6 mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            LLM settings unavailable — using defaults
          </div>
        )}

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
                <MessageBubble
                  key={msg.id}
                  msg={msg}
                  effectiveDocId={effectiveDocId}
                  onQuizSubmit={sendMessage}
                  navigateToCitation={navigateToCitation}
                />
              ))}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {/* S187/S196: contextual suggestion pills (also shown after a scope-change divider).
            Renders in scope="all" too -- the backend produces cross-document
            onboarding/exploration suggestions when document_id is null. */}
        {(messages.length === 0 || messages[messages.length - 1]?.type === "divider") && (
          <SuggestionPills
            documentId={scope === "single" ? effectiveDocId : null}
            onSuggest={(text) => void sendMessage(text)}
          />
        )}

        <SessionPlanPanel
          open={showPlanPanel}
          onClose={() => setShowPlanPanel(false)}
          plan={sessionPlan}
          loading={planLoading}
          error={planError}
          onRetry={() => void refetchPlan()}
          onNavigate={(target) => navigate(target)}
        />

        {/* Input */}
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
    </div>
  )
}
