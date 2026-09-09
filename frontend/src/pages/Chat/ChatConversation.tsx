import { useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, ArrowLeft, BookMarked, BookOpen, PanelLeft, PanelLeftClose, RefreshCw, Send, Settings, Sparkles, Trash2, WifiOff, X } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { useBackNavigation } from "@/hooks/useBackNavigation"
import { toast } from "sonner"
import { ModelSelector } from "@/components/ModelSelector"
import { fetchLLMSettings } from "@/lib/llmSettings"
import { ChatSessionList } from "@/components/chat/ChatSessionList"
import { LuminaryGlyph } from "@/components/icons/LuminaryGlyph"
import {
  appendChatMessage,
  createChatSession,
  deleteChatSession,
  getChatSession,
  renameChatSession,
  updateChatSessionModel,
} from "@/lib/chatSessionsApi"
import { Badge } from "@/components/ui/badge"
import { SourceCitationChips } from "@/components/SourceCitationChips"
import type { SourceCitation } from "@/components/SourceCitationChips"
import { GapResultCard } from "@/components/GapResultCard"
import type { GapCardData } from "@/components/GapResultCard"
import { QuizQuestionCard } from "@/components/QuizQuestionCard"
import { VoiceRecordButton } from "@/components/VoiceRecordButton"
import { TeachBackResultCard } from "@/components/TeachBackResultCard"
import type { TeachBackCardData } from "@/components/TeachBackResultCard"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { ChatSettingsDrawer } from "@/components/ChatSettingsDrawer"
import { Skeleton } from "@/components/ui/skeleton"
import { logger } from "@/lib/logger"
import { useAppStore } from "@/store"
import { PAGE_THREAD, preloadIsFor, threadOf } from "@/store/chatThreads"
import { buildModelOptions, cloudOverrideAllowed, effectiveDefaultModel, shouldClearPrivateModeOverride } from "@/lib/chatSettingsUtils"

import { API_BASE } from "@/lib/config"
import { apiGet } from "@/lib/apiClient"
import { buildCitationTarget, targetToStateValue } from "@/lib/citation"

import { AnswerReceiptLine } from "./AnswerReceiptLine"
import { ChatEmptyState } from "./ChatEmptyState"
import { DocumentScopeCombobox } from "./DocumentScopeCombobox"
import { SuggestionPills } from "./SuggestionPills"
import { TransparencyPanel } from "./TransparencyPanel"
import { CONFIDENCE_BADGE } from "./constants"
import { fetchDocList, labelledCitations, persistedToChatMessage } from "./api"
import type {
  AnswerReceipt,
  AnyCardData,
  ChatMessage,
  Citation,
  Confidence,
  QuizCardData,
  SessionPlanResponse,
  TransparencyInfo,
  WebSearchSettings,
  WebSource,
} from "./types"

/**
 * One chat conversation: its thread, its composer, and the session list beside it.
 *
 * A component rather than a page because the reader docks it: the rung that owns
 * this panel replaces three modals with tabs, and `Ask AI` is this. What differs
 * between the two mounts is chrome, not conversation -- a dock has no session
 * list, no back button and no `?q=` to consume -- so `variant` gates exactly
 * those and nothing about how a question is asked or answered.
 *
 * Scope is read from the store at send time, never from the render closure
 * (`957b5be`): a question sent from here must be scoped to what the chip says,
 * not to whatever document the reader happened to open while it was streaming.
 */
export function ChatConversation({
  variant = "page",
  threadKey = PAGE_THREAD,
  pinnedDocumentId,
  onCitationInDocument,
}: {
  variant?: "page" | "docked"
  threadKey?: string
  /** Docked beside a document: its scope, and not the reader's to change. */
  pinnedDocumentId?: string
  /** Answer a citation without routing. Returns whether it was handled here. */
  onCitationInDocument?: (c: SourceCitation) => boolean
} = {}) {
  const isPage = variant === "page"
  const activeDocumentId = useAppStore((s) => s.activeDocumentId)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const chatPreload = useAppStore((s) => s.chatPreload)
  const clearChatPreload = useAppStore((s) => s.clearChatPreload)
  const navigate = useNavigate()
  const { canGoBack, backLabel, goBack } = useBackNavigation()
  const [searchParams] = useSearchParams()
  const qc = useQueryClient()
  // Every piece of conversation state is read out of this surface's own thread,
  // so a conversation docked in a reader neither reads nor rewrites the Ask
  // page's. `here()` is the same read outside render, for the streaming path,
  // which must never work from a closure (957b5be).
  const thread = useAppStore((s) => threadOf(s.chatThreads, threadKey))
  const patchThread = useAppStore((s) => s.setChatThread)
  const here = useCallback(
    () => threadOf(useAppStore.getState().chatThreads, threadKey),
    [threadKey],
  )
  const messages = thread.messages as ChatMessage[]
  const setMessages = useCallback(
    (updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => {
      patchThread(threadKey, {
        messages: typeof updater === "function" ? updater(here().messages as ChatMessage[]) : updater,
      })
    },
    [patchThread, threadKey, here],
  )
  const [input, setInput] = useState("")
  const scope = thread.scope
  const setScope = useCallback(
    (next: "single" | "all") => patchThread(threadKey, { scope: next }),
    [patchThread, threadKey],
  )
  // selectedDocId: explicit in-tab selection; falls back to global activeDocumentId
  const selectedDocId = thread.selectedDocId
  const setSelectedDocId = useCallback(
    (id: string | null) => patchThread(threadKey, { selectedDocId: id }),
    [patchThread, threadKey],
  )
  const [model, setModel] = useState<string>("")
  const [isStreaming, setIsStreaming] = useState(false)
  const qaError = thread.error
  const setQaError = useCallback(
    (err: string | null) => patchThread(threadKey, { error: err }),
    [patchThread, threadKey],
  )
  const activeSessionId = thread.sessionId
  const setActiveSessionId = useCallback(
    (id: string | null) => patchThread(threadKey, { sessionId: id }),
    [patchThread, threadKey],
  )
  const sidebarOpen = useAppStore((s) => s.chatSidebarOpen)
  const setSidebarOpen = useAppStore((s) => s.setChatSidebarOpen)
  const llmMode = useAppStore((s) => s.llmMode)
  const [hydratingSession, setHydratingSession] = useState(false)
  const [webEnabled, setWebEnabled] = useState(false)
  const [creativeEnabled, setCreativeEnabled] = useState(false)
  const [webCallsUsed, setWebCallsUsed] = useState(0)
  const [showPlanPanel, setShowPlanPanel] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const mountTime = useRef(Date.now())
  const didInitialHydrate = useRef(false)
  const handledPreloadRef = useRef<object | null>(null)

  // Document list for the "This document" picker
  const { data: docList } = useQuery({
    queryKey: ["chat-doc-list"],
    queryFn: fetchDocList,
    staleTime: 30_000,
  })

  // A selected document that is no longer in the library must not scope a search.
  // chatSelectedDocId is persisted, and deleting a document never cleared it, so a
  // chat could stay pointed at a document that had been gone for days: the header
  // showed "All documents" (a missing id has no title to render) while every
  // question was filtered down to that one dead id and answered nothing.
  useEffect(() => {
    if (!docList || !selectedDocId) return
    if (docList.some((d) => d.id === selectedDocId)) return
    setSelectedDocId(null)
    setScope("all")
  }, [docList, selectedDocId, setSelectedDocId, setScope])

  // Pre-populate from global store when user arrives from Learning tab.
  // Use a ref to avoid re-populating after the user explicitly clears
  // the document selection (clicking the X button).
  const docSelectorTouched = useRef(false)

  // A pinned conversation is about one document and cannot be re-scoped: it is
  // docked beside that document, and the reader asking about the page in front
  // of them means this document, whatever the Ask page is scoped to.
  useEffect(() => {
    if (!pinnedDocumentId) return
    if (thread.selectedDocId === pinnedDocumentId && thread.scope === "single") return
    patchThread(threadKey, { selectedDocId: pinnedDocumentId, scope: "single" })
  }, [pinnedDocumentId, thread.selectedDocId, thread.scope, patchThread, threadKey])

  useEffect(() => {
    if (pinnedDocumentId) return
    if (activeDocumentId && !selectedDocId && !docSelectorTouched.current) {
      setSelectedDocId(activeDocumentId)
      setScope("single")
    }
  }, [activeDocumentId, selectedDocId, pinnedDocumentId]) // eslint-disable-line react-hooks/exhaustive-deps

  // S147: Pre-fill input from chatPreload set by SelectionActionBar "Ask in Chat" action
  // S197: autoSubmit flag triggers immediate send
  useEffect(() => {
    // Guard against StrictMode's double effect invocation (both share this
    // render's closure, so the chatPreload check alone would fire the send
    // twice). Key on the preload object identity so a later "Ask" still runs.
    if (chatPreload && preloadIsFor(chatPreload, threadKey) && handledPreloadRef.current !== chatPreload) {
      handledPreloadRef.current = chatPreload
      const shouldAutoSubmit = chatPreload.autoSubmit
      // "Ask" from the reader always starts a fresh conversation rather than
      // appending to whatever session happened to be active. Suppress the
      // one-shot mount hydration so it can't reload the prior session over us.
      didInitialHydrate.current = true
      startNewChat()
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
    if (!isPage) return
    const prefill = searchParams.get("q")
    if (prefill) {
      setInput(prefill)
    }
  }, [searchParams, isPage])

  const { data: llmSettings, isLoading: llmLoading, isError: llmError } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: fetchLLMSettings,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  })

  const { data: webSearchSettings } = useQuery<WebSearchSettings>({
    queryKey: ["web-search-settings"],
    queryFn: () => apiGet<WebSearchSettings>("/settings/web-search"),
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
    queryFn: () => apiGet<SessionPlanResponse>("/study/session-plan", { minutes: 20 }),
    enabled: showPlanPanel,
    staleTime: 60_000,
  })

  const modelOptions = buildModelOptions(llmSettings)

  // Cloud models for the configured provider, so the header selector can offer
  // a frontier model per-conversation (the /qa model override routes to it
  // directly). Not fetched in Private mode: "All processing on-device via
  // Ollama" is the promise of that mode, so a cloud model must never even be
  // offered as a per-conversation override there.
  const chatProvider = llmSettings?.provider
  const cloudAllowed = cloudOverrideAllowed(llmSettings?.mode)
  const { data: cloudModelList } = useQuery({
    queryKey: ["chat-cloud-models", chatProvider],
    queryFn: () =>
      apiGet<{ id: string }[]>("/settings/llm/models", { provider: chatProvider as string }),
    enabled: Boolean(chatProvider) && cloudAllowed,
    staleTime: 300_000,
  })
  const localModelChoices = llmSettings?.available_local_models ?? []
  // Guard against a stale cache too: react-query keeps the last-fetched list
  // around when a query goes from enabled to disabled, so a provider fetched
  // before switching to Private must not leak through here.
  const cloudModelChoices = cloudAllowed
    ? (cloudModelList ?? []).map((m) => `${chatProvider}/${m.id}`)
    : []
  const effectiveModel = effectiveDefaultModel(llmSettings)

  // A per-conversation override chosen back in Cloud/Hybrid mode must not keep
  // pinning a cloud model once the user switches to Private -- that mode's
  // promise is on-device only, and the stale override would still be sent to
  // /qa even though the dropdown no longer offers it. Derived rather than
  // cleared: the stored choice is left intact so switching back to Cloud
  // restores it, and every send below reads `activeModel`, never `model`.
  const activeModel = shouldClearPrivateModeOverride(llmSettings?.mode, model) ? "" : model

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

  // Hydrate from server explicitly. Used on initial mount for a persisted
  // session id and whenever the user clicks an entry in the sidebar.
  // We deliberately do NOT auto-hydrate on every activeSessionId change, because
  // sendMessage and switchContextWithUndo also flip activeSessionId, and a
  // hydration race during streaming would clobber the in-flight assistant turn.
  async function hydrateSession(id: string) {
    setHydratingSession(true)
    try {
      const sess = await getChatSession(id)
      const hydrated: ChatMessage[] = sess.messages.map(persistedToChatMessage)
      setMessages(hydrated)
      setScope(sess.scope)
      setSelectedDocId(sess.document_ids[0] ?? null)
      // The hydrated session owns the doc context now. Without this, restoring
      // an all-scope session (selectedDocId -> null) re-arms the Learning-tab
      // pre-populate effect, which stamps activeDocumentId back on as "single".
      docSelectorTouched.current = true
      setModel(sess.model ?? llmSettings?.active_model ?? "")
      setQaError(null)
    } catch {
      // Session disappeared (deleted in another tab) -- start fresh.
      setActiveSessionId(null)
      setMessages([])
    } finally {
      setHydratingSession(false)
    }
  }

  // One-shot hydration for the persisted active session at mount time.
  useEffect(() => {
    if (didInitialHydrate.current) return
    didInitialHydrate.current = true
    const persistedId = here().sessionId
    if (persistedId) {
      void hydrateSession(persistedId)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function startNewChat() {
    setActiveSessionId(null)
    setMessages([])
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
    // With persistence, Clear means "start a new chat" -- the prior thread is preserved
    // in the sidebar.
    startNewChat()
  }

  async function switchContextWithUndo(
    nextScope: "single" | "all",
    nextDocId: string | null,
  ) {
    // Snapshot for undo
    const prevSessionId = here().sessionId
    const prevMessages = here().messages as ChatMessage[]
    const prevScope = scope
    const prevDocId = selectedDocId
    const labelDoc =
      nextScope === "single" && nextDocId
        ? (docList?.find((d) => d.id === nextDocId)?.title ?? "this document")
        : "All documents"

    // Empty conversation -> just update context, no session split needed.
    if (prevMessages.length === 0 || !prevSessionId) {
      setScope(nextScope)
      setSelectedDocId(nextDocId)
      return
    }

    try {
      const created = await createChatSession({
        scope: nextScope,
        document_ids: nextScope === "single" && nextDocId ? [nextDocId] : [],
        model: activeModel || null,
      })
      setActiveSessionId(created.id)
      setMessages([])
      setScope(nextScope)
      setSelectedDocId(nextDocId)
      void qc.invalidateQueries({ queryKey: ["chat-sessions"] })

      toast(`New chat for ${labelDoc}`, {
        action: {
          label: "Undo",
          onClick: () => {
            // Discard the empty session and restore the prior conversation.
            void deleteChatSession(created.id).catch(() => {})
            setActiveSessionId(prevSessionId)
            setMessages(prevMessages)
            setScope(prevScope)
            setSelectedDocId(prevDocId)
            void qc.invalidateQueries({ queryKey: ["chat-sessions"] })
          },
        },
        duration: 6000,
      })
    } catch (err) {
      logger.warn("[Chat] switchContextWithUndo failed", { err: String(err) })
      // Fall back to in-place context switch if session creation breaks.
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

  async function sendMessage(question: string, opts?: { reuseUserTurn?: boolean }) {
    if (!question.trim() || isStreaming) return
    setInput("")
    if (textareaRef.current) textareaRef.current.style.height = "auto"

    // Read scope/doc from the store, not the render closure: callers like the
    // reader "Ask" flow set these via state and immediately invoke sendMessage,
    // so the closure values would be stale and retrieval would run unscoped.
    //
    // The document comes from the chat's own selection and nowhere else. It used
    // to fall back to activeDocumentId -- the file last opened in the reader --
    // which is not a chat scope: with chatScope left at "single" and nothing
    // selected here, a question went out scoped to whatever document the user had
    // just opened or uploaded, while the header chip (which reads selectedDocId,
    // not scope) said "All documents". Seen 2026-08-17: a library question landed
    // on a PDF 40 seconds into ingestion and came back empty. If the scope says
    // single but this chat has no document, the chip is right and the scope is
    // stale -- ask the whole library, which is what the user is being shown.
    const st = here()
    const effSelectedDocId = st.selectedDocId
    const effScope = st.scope === "single" && !effSelectedDocId ? "all" : st.scope

    // Resolve / create the persisted session before we start streaming, so we have
    // a stable id to attach both the user turn and the assistant turn to.
    const sessionDocIds =
      effScope === "single" && effSelectedDocId ? [effSelectedDocId] : []
    let sessionId = here().sessionId
    const isFirstTurn =
      !sessionId ||
      (here().messages as ChatMessage[]).length === 0
    if (!sessionId) {
      try {
        const created = await createChatSession({
          scope: effScope,
          document_ids: sessionDocIds,
          model: activeModel || null,
        })
        sessionId = created.id
        setActiveSessionId(created.id)
        void qc.invalidateQueries({ queryKey: ["chat-sessions"] })
      } catch (err) {
        logger.warn("[Chat] session create failed; falling back to ephemeral", { err: String(err) })
        sessionId = null
      }
    }

    const assistantId = crypto.randomUUID()
    const assistantMsg: ChatMessage = { id: assistantId, role: "assistant", text: "", isStreaming: true }
    // On retry the user turn is already in the thread and already persisted, so
    // reuse it -- re-adding would duplicate the question on the backend session.
    if (opts?.reuseUserTurn) {
      setMessages((m) => [...m, assistantMsg])
    } else {
      const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", text: question }
      setMessages((m) => [...m, userMsg, assistantMsg])
    }
    setIsStreaming(true)

    if (sessionId && !opts?.reuseUserTurn) {
      void appendChatMessage(sessionId, { role: "user", content: question }).catch(() => {})
    }

    try {
      const documentIds = effScope === "single" && effSelectedDocId ? [effSelectedDocId] : null

      // Collect last 6 completed messages (3 exchanges) as conversation history.
      // Excludes the current streaming placeholder and not_found messages.
      const historySlice = messages
        .filter((m) => !m.isStreaming && !m.not_found && m.text && m.type !== "divider")
        .slice(-6)
        .map((m) => ({ role: m.role, content: m.text }))

      // SSE stream: tokens arrive via res.body.getReader(); apiClient's
      // JSON path doesn't apply.
      // eslint-disable-next-line no-restricted-syntax
      const res = await fetch(`${API_BASE}/qa`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          document_ids: documentIds,
          scope: effScope,
          model: activeModel || null,
          messages: historySlice.length > 0 ? historySlice : undefined,
          web_enabled: webEnabled,
          creative: creativeEnabled,
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

            // Offline / routing notice — non-fatal, shown inline above the answer.
            if (payload["type"] === "notice" && typeof payload["message"] === "string") {
              const noticeText = payload["message"] as string
              setMessages((m) =>
                m.map((msg) =>
                  msg.id === assistantId ? { ...msg, notice: noticeText } : msg,
                ),
              )
            }

            // S158: transparency event arrives before 'done' — silently omit if malformed
            // Sources arrive before the first token, so the chips paint while the
            // answer is still generating instead of appearing with it. On the local
            // arm time-to-first-token is tens of seconds, and every one of them
            // used to show an empty panel. The `done` payload sends these again and
            // overwrites this, so a stale set cannot survive the turn.
            if (payload["type"] === "sources") {
              const early = (payload["source_citations"] as SourceCitation[] | undefined) ?? []
              if (early.length > 0) {
                setMessages((m) =>
                  m.map((msg) =>
                    msg.id === assistantId ? { ...msg, source_citations: early } : msg,
                  ),
                )
              }
            }

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

            // SSE error event — mark this turn failed so it can be retried inline.
            if (typeof payload["error"] === "string") {
              const errorCode = payload["error"] as string
              const fallbackMsg = (payload["message"] as string | undefined) ?? "An error occurred."
              // Only llm_unavailable is reworded here, because the right wording
              // depends on llmMode, which is client state. Retrieval failures
              // carry a server message that names which of them happened.
              const errorMsg =
                errorCode === "llm_unavailable"
                  ? (llmMode === "private"
                      ? "Ollama is not running. Start it with: ollama serve"
                      : "LLM service is unreachable. Please check your internet connection or settings.")
                  : fallbackMsg
              setIsStreaming(false)
              setMessages((m) =>
                m.map((msg) =>
                  msg.id === assistantId
                    ? { ...msg, isStreaming: false, text: "", error: errorMsg, failedQuestion: question }
                    : msg,
                ),
              )
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
              const receipt = payload["receipt"] as AnswerReceipt | undefined
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
                      receipt,
                    }
                    : msg,
                ),
              )
              setIsStreaming(false)
              // S195: refresh suggestion pills after each answered question
              const suggestDocId = effScope === "single" ? effSelectedDocId : null
              void qc.invalidateQueries({ queryKey: ["chat-suggestions", suggestDocId] })

              // Persist the assistant turn + refresh sidebar list. For brand-new
              // sessions also fire an LLM auto-title in the background.
              if (sessionId) {
                const finalText =
                  finalAnswer !== undefined
                    ? finalAnswer
                    : (here().messages as ChatMessage[]).find(
                      (mm) => mm.id === assistantId,
                    )?.text ?? ""
                const transparencyAtDone = (here().messages as ChatMessage[]).find(
                  (mm) => mm.id === assistantId,
                )?.transparency
                void appendChatMessage(sessionId, {
                  role: "assistant",
                  content: finalText,
                  extra: {
                    citations,
                    confidence,
                    image_ids,
                    web_sources,
                    source_citations,
                    not_found,
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
            }
          } catch {
            // skip malformed SSE event
          }
        }
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err)
      logger.error("[Chat] fetch failed", { endpoint: "/qa", error: errMsg })
      const shown =
        errMsg.includes("Failed to fetch") || errMsg.includes("NetworkError")
          ? "Cannot reach the server. Is the backend running on port 7820?"
          : `Could not get a response: ${errMsg}`
      setMessages((m) =>
        m.map((msg) =>
          msg.id === assistantId
            ? { ...msg, isStreaming: false, text: "", error: shown, failedQuestion: question }
            : msg,
        ),
      )
      setIsStreaming(false)
    }
  }

  // Re-send a failed turn. The user turn stays (already shown and persisted); we
  // drop only the errored assistant bubble and stream a fresh answer for it.
  function retryMessage(assistantId: string, question: string) {
    if (isStreaming || !question.trim()) return
    setMessages((m) => m.filter((msg) => msg.id !== assistantId))
    void sendMessage(question, { reuseUserTurn: true })
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      void sendMessage(input)
    }
  }

  // S148: navigate to Learning tab with DocumentReader open at the cited section/page
  function navigateToCitation(c: SourceCitation) {
    // A conversation docked beside a document answers a citation into that same
    // document where it stands. Routing remounts the reader from the URL, which
    // takes the panel the citation was clicked in down with it -- the passage
    // arrives and the conversation the reader was holding is gone.
    if (onCitationInDocument?.(c)) return
    setActiveDocument(c.document_id)
    // Close the chat side-panel if open, so user sees the document
    const params = new URLSearchParams()
    params.set("doc", c.document_id)
    if (c.section_id) params.set("section_id", c.section_id)
    if (c.chunk_id) params.set("chunk_id", c.chunk_id)
    if (c.pdf_page_number) params.set("page", String(c.pdf_page_number))
    // The snippet rides along so the reader can mark the exact words in the prose.
    // It is already in hand here; fetching the chunk again in the reader would cost
    // a request that returns every chunk in the document to use one of them.
    navigate(`/library?${params.toString()}`, {
      state: { from: "/chat", citationWords: targetToStateValue(buildCitationTarget(c)) },
    })
  }

  const effectiveDocId = selectedDocId ?? activeDocumentId
  const noDocumentSelected = scope === "single" && !effectiveDocId

  return (
    <div className="flex h-full">
      {isPage && sidebarOpen && (
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
      {/* Header controls */}
      <div className="sticky top-0 z-20 flex items-center gap-2 border-b border-border bg-background/80 px-6 py-2.5 backdrop-blur-md supports-[backdrop-filter]:bg-background/60">
        {isPage && canGoBack && (
          <button
            onClick={goBack}
            className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <ArrowLeft size={12} />
            {backLabel}
          </button>
        )}
        {isPage && (
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
          title={sidebarOpen ? "Hide chat list" : "Show chat list"}
          aria-label={sidebarOpen ? "Hide chat list" : "Show chat list"}
        >
          {sidebarOpen ? <PanelLeftClose size={15} /> : <PanelLeft size={15} />}
        </button>
        )}
        {hydratingSession && (
          <span className="text-xs text-muted-foreground">Loading chat...</span>
        )}
        {/* S186: Inline document scope combobox */}
        {!pinnedDocumentId && (
        <DocumentScopeCombobox
          docList={docList}
          selectedDocId={selectedDocId}
          onSelect={(docId) => {
            docSelectorTouched.current = true
            // Whenever the context (scope or selected book) changes mid-conversation,
            // we start a new persisted chat. The user can undo from the toast.
            if (docId === null) {
              if (scope !== "all" || selectedDocId !== null) {
                void switchContextWithUndo("all", null)
              }
            } else if (docId !== selectedDocId || scope === "all") {
              void switchContextWithUndo("single", docId)
            }
          }}
        />
        )}

        {/* Inline model indicator + per-conversation override */}
        {!llmLoading && llmSettings && (
          <ModelSelector
            value={activeModel}
            onChange={(m) => {
              setModel(m)
              const sid = here().sessionId
              if (sid) void updateChatSessionModel(sid, m || null).catch(() => {})
            }}
            localModels={localModelChoices}
            cloudModels={cloudModelChoices}
            effectiveDefault={effectiveModel}
          />
        )}

        <div className="ml-auto flex items-center gap-2">
          {/* Creative mode -- primary per-question toggle (grounded generative answers) */}
          <button
            onClick={() => setCreativeEnabled((prev) => !prev)}
            aria-pressed={creativeEnabled}
            title={
              creativeEnabled
                ? "Creative mode is on: imaginative answers grounded in your material. Click for strict, cited answers."
                : "Creative mode: turn answers into stories, poems, and analogies grounded in your own material."
            }
            className={`flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-all duration-200 ${
              creativeEnabled
                ? "border-purple-300 bg-purple-50 text-purple-700 shadow-[0_0_0_3px_rgba(168,85,247,0.12)] dark:border-purple-800 dark:bg-purple-950/40 dark:text-purple-300"
                : "border-border text-muted-foreground hover:border-purple-200 hover:bg-accent hover:text-foreground"
            }`}
          >
            <Sparkles size={13} className={creativeEnabled ? "text-purple-500" : ""} />
            Creative
          </button>

          {/* Web call counter -- shown when web is enabled and conversation is active */}
          {webEnabled && messages.length > 0 && (
            <span className="rounded-full bg-muted px-2 py-1 text-xs tabular-nums text-muted-foreground">
              Web {webCallsUsed}/3
            </span>
          )}

          {/* Clear conversation button -- only shown when there are messages */}
          {messages.length > 0 && !isStreaming && (
            <button
              onClick={clearConversation}
              className="flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
              title="Clear conversation"
            >
              <Trash2 size={13} />
              Clear
            </button>
          )}

          {/* Settings gear icon -- opens ChatSettingsDrawer */}
          <button
            onClick={() => setSettingsOpen(true)}
            className="rounded-full p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
            title="Chat settings"
          >
            <Settings size={15} />
          </button>
        </div>
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
        <div className="mx-6 mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
          LLM settings unavailable — using defaults
        </div>
      )}

      {/* QA error banner — inline amber alert */}
      {qaError && (
        <div className="mx-6 mt-2 flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          <span className="flex-1">{qaError}</span>
          <button onClick={() => setQaError(null)} className="hover:text-amber-900" aria-label="Dismiss">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Message list */}
      <div className="flex-1 overflow-auto px-6 py-6">
        {llmLoading ? (
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-3 py-4">
            <Skeleton className="h-10 w-3/4 self-end" />
            <Skeleton className="h-16 w-2/3" />
            <Skeleton className="h-10 w-1/2 self-end" />
          </div>
        ) : noDocumentSelected ? (
          <ChatEmptyState
            title="Pick something to study"
            body="Open a document in the Learning tab, then come back here to ask questions about it."
          />
        ) : messages.length === 0 ? (
          hasDocuments === false ? (
            <ChatEmptyState
              title="Your library is empty"
              body="Upload a document in the Learning tab and Luminary will answer from it, with citations."
            />
          ) : (
            <ChatEmptyState
              title="Ask anything about your material"
              body="Every answer is grounded in your own documents and cites where it came from."
            />
          )
        ) : (
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
            {messages.map((msg) => (
              msg.type === "divider" ? (
                <div key={msg.id} className="flex items-center gap-3 py-1">
                  <div className="h-px flex-1 bg-gradient-to-r from-transparent to-border" />
                  <span className="rounded-full border border-border bg-muted/50 px-2.5 py-0.5 text-xs text-muted-foreground">
                    {msg.text}
                  </span>
                  <div className="h-px flex-1 bg-gradient-to-l from-transparent to-border" />
                </div>
              ) : (
                <div
                  key={msg.id}
                  className={`lum-msg-enter flex items-start gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  {msg.role !== "user" && (
                    <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-primary/20 bg-gradient-to-br from-primary/15 to-purple-500/10">
                      <LuminaryGlyph size={16} />
                    </div>
                  )}
                  <div
                    className={`max-w-[80%] px-4 py-3 transition-shadow ${msg.role === "user"
                        ? "rounded-2xl rounded-br-md bg-primary text-primary-foreground shadow-[var(--shadow-md)]"
                        : "rounded-2xl rounded-tl-md border border-border bg-card text-card-foreground shadow-[var(--shadow-sm)] hover:shadow-[var(--shadow-md)]"
                      }`}
                  >
                    {msg.notice && msg.role === "assistant" && (
                      <div className="mb-2 flex items-center gap-1.5 rounded-md border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-xs text-amber-700 dark:text-amber-400">
                        <WifiOff size={12} className="shrink-0" />
                        <span>{msg.notice}</span>
                      </div>
                    )}
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
                    ) : msg.error ? (
                      <div className="space-y-2">
                        <p className="flex items-start gap-1.5 text-sm text-destructive">
                          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                          <span>{msg.error}</span>
                        </p>
                        <button
                          onClick={() => retryMessage(msg.id, msg.failedQuestion ?? "")}
                          disabled={isStreaming || !msg.failedQuestion}
                          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground hover:bg-muted disabled:opacity-50"
                        >
                          <RefreshCw size={12} />
                          Retry
                        </button>
                      </div>
                    ) : msg.not_found ? (
                      <p className="text-sm text-blue-600">
                        This information was not found in the selected content.
                      </p>
                    ) : msg.role === "user" ? (
                      <p className="whitespace-pre-wrap text-sm">{msg.text}</p>
                    ) : msg.isStreaming && msg.text === "" ? (
                      // Shown while waiting for a card SSE event (e.g. quiz, teach-back, gap)
                      // or before the first token of a streamed text response arrives.
                      <div className="flex items-center gap-1.5 py-1" role="status" aria-label="Thinking">
                        <span className="lum-typing-dot h-2 w-2 rounded-full bg-primary" />
                        <span className="lum-typing-dot h-2 w-2 rounded-full bg-primary" />
                        <span className="lum-typing-dot h-2 w-2 rounded-full bg-primary" />
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
                        {msg.isStreaming && (
                          <span className="ml-0.5 inline-block h-4 w-[3px] animate-pulse rounded-full bg-primary align-text-bottom" />
                        )}
                      </div>
                    )}

                    {/* Citations and confidence — shown after streaming completes.
                        Citations the model quoted without a title or page cannot be
                        labelled (they render as "Doc" or a bare ellipsis) and the
                        source chips below already carry the same grounding with
                        real titles and pages, so they are dropped rather than shown
                        as blanks. */}
                    {!msg.isStreaming && labelledCitations(msg.citations).length > 0 && (
                      <div className="mt-3 space-y-2">
                        <div className="flex flex-wrap gap-1.5">
                          {labelledCitations(msg.citations).map((c, i) => (
                            <span
                              key={i}
                              className="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                              title={c.excerpt}
                            >
                              {c.document_title
                                ? `${c.document_title.slice(0, 20)}${c.document_title.length > 20 ? "…" : ""}${c.page > 0 ? ` · p.${c.page}` : ""}`
                                : c.page > 0 ? `p.${c.page}` : "Doc"}
                              {c.version_mismatch && (
                                <span className="ml-1 rounded-full border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                                  Version mismatch
                                </span>
                              )}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* TransparencyPanel renders the same value with an
                        explanation, so only stand in when it is absent. */}
                    {!msg.isStreaming && msg.confidence && !msg.transparency && (
                      <div className="mt-3">
                        <Badge variant={CONFIDENCE_BADGE[msg.confidence]}>
                          {msg.confidence} confidence
                        </Badge>
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

                    {/* What this answer cost, and whether it left the machine */}
                    {!msg.isStreaming && msg.receipt && (
                      <AnswerReceiptLine receipt={msg.receipt} />
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
      <div className="border-t border-border bg-background px-6 py-4">
        <div className="mx-auto w-full max-w-3xl">
          <div className="lum-composer flex items-end gap-2 rounded-2xl border border-border bg-card p-2 shadow-[var(--shadow-sm)]">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value)
                autoResize()
              }}
              onKeyDown={handleKeyDown}
              placeholder={noDocumentSelected ? "Select a document first..." : "Ask a question about your material..."}
              disabled={noDocumentSelected || isStreaming}
              rows={1}
              className="flex-1 resize-none bg-transparent px-2 py-1.5 text-sm leading-relaxed text-foreground placeholder:text-muted-foreground focus:outline-none disabled:opacity-50"
            />
            <VoiceRecordButton
              size="default"
              className="h-9 w-9 p-0 rounded-xl shrink-0"
              onTranscribed={(text) => {
                setInput((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text))
                setTimeout(() => {
                  if (textareaRef.current) {
                    textareaRef.current.style.height = "auto"
                    textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`
                  }
                }, 0)
              }}
              title="Dictate question with voice (Whisper)"
            />
            <button
              onClick={() => void sendMessage(input)}
              disabled={!input.trim() || isStreaming || noDocumentSelected}
              aria-label="Send message"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-[var(--shadow-sm)] transition-all duration-200 hover:bg-primary/90 hover:shadow-[var(--shadow-md)] active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none disabled:hover:bg-primary"
            >
              <Send size={15} />
            </button>
          </div>
          <p className="mt-2 text-center text-xs text-muted-foreground/70">
            Enter to send · Shift+Enter for newline
          </p>
        </div>
      </div>
      </div>
    </div>
  )
}
