import { Loader2, RefreshCw } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { API_BASE } from "@/lib/config"
import { cn } from "@/lib/utils"

import { GlossaryPanel } from "./GlossaryPanel"
import { NotesReaderPanel } from "./NotesReaderPanel"
import { ReferencesPanel } from "./ReferencesPanel"
import { CONVERSATION_TAB, SUMMARY_TABS, type SummaryMode, type SummaryTabDef } from "./types"

type SummaryMap = Partial<Record<SummaryMode, string>>
type StreamingMap = Partial<Record<SummaryMode, boolean>>

type PanelTab = SummaryMode | "glossary" | "references" | "notes"

interface SummaryPanelProps {
  documentId: string
  contentType: string
  activeSectionId?: string | null
  onScrollToSection?: (sectionId: string) => void
  onNoteCountKnown: (count: number) => void
}

export function SummaryPanel({ documentId, contentType, activeSectionId, onScrollToSection, onNoteCountKnown }: SummaryPanelProps) {
  const summaryTabs: SummaryTabDef[] =
    contentType === "conversation" ? [...SUMMARY_TABS, CONVERSATION_TAB] : SUMMARY_TABS
  const allTabs = [
    { mode: "notes" as PanelTab, label: "Notes" },
    ...summaryTabs.map((t) => ({ mode: t.mode as PanelTab, label: t.label })),
    { mode: "glossary" as PanelTab, label: "Glossary" },
    { mode: "references" as PanelTab, label: "References" },
  ]

  const [activeTab, setActiveTab] = useState<PanelTab>("notes")
  const defaultTabResolved = useRef(false)
  const [summaries, setSummaries] = useState<SummaryMap>({})
  const [streaming, setStreaming] = useState<StreamingMap>({})
  const [summaryError, setSummaryError] = useState<string | null>(null)
  const [cacheLoading, setCacheLoading] = useState(true)

  const handleNoteCountKnown = useCallback((count: number) => {
    onNoteCountKnown(count)
    if (!defaultTabResolved.current) {
      defaultTabResolved.current = true
      if (count === 0) {
        setActiveTab("executive")
      }
    }
  }, [onNoteCountKnown])

  useEffect(() => {
    let cancelled = false
    async function loadCached() {
      try {
        const res = await fetch(`${API_BASE}/summarize/${documentId}/cached`)
        if (!res.ok || cancelled) return
        const data = (await res.json()) as {
          summaries: Record<string, { id: string; content: string }>
        }
        if (cancelled) return
        const loaded: SummaryMap = {}
        for (const [mode, s] of Object.entries(data.summaries)) {
          loaded[mode as SummaryMode] = s.content
        }
        setSummaries(loaded)
      } catch {
        // cache unavailable -- user can still generate manually
      } finally {
        if (!cancelled) setCacheLoading(false)
      }
    }
    void loadCached()
    return () => { cancelled = true }
  }, [documentId])

  async function generateSummary(mode: SummaryMode, forceRefresh = false) {
    setSummaryError(null)

    if (!forceRefresh) {
      try {
        const cacheRes = await fetch(`${API_BASE}/summarize/${documentId}/cached`)
        if (cacheRes.ok) {
          const cacheData = (await cacheRes.json()) as {
            summaries: Record<string, { id: string; content: string }>
          }
          if (cacheData.summaries[mode]) {
            setSummaries((s) => ({ ...s, [mode]: cacheData.summaries[mode].content }))
            return
          }
        }
      } catch {
        // cache check failed -- fall through to streaming
      }
    }

    setStreaming((s) => ({ ...s, [mode]: true }))
    setSummaries((s) => ({ ...s, [mode]: "" }))
    try {
      const res = await fetch(`${API_BASE}/summarize/${documentId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, model: null, force_refresh: forceRefresh }),
      })
      if (!res.ok || !res.body) throw new Error("Summarization failed")
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
          if (line.startsWith("data: ")) {
            try {
              const payload = JSON.parse(line.slice(6)) as Record<string, unknown>
              if (typeof payload["token"] === "string") {
                setSummaries((s) => ({ ...s, [mode]: (s[mode] ?? "") + payload["token"] }))
              }
              if (payload["error"] === "llm_unavailable") {
                setSummaryError(typeof payload["message"] === "string" ? payload["message"] : "Ollama is not running. Start it with: ollama serve")
              }
              if (payload["done"] === true) {
                setStreaming((s) => ({ ...s, [mode]: false }))
              }
            } catch {
              // skip malformed SSE event
            }
          }
        }
      }
    } catch {
      setStreaming((s) => ({ ...s, [mode]: false }))
      setSummaryError("Ollama is not running. Start it with: ollama serve")
    }
  }

  const isSidePanel = activeTab === "glossary" || activeTab === "references" || activeTab === "notes"
  const currentSummary = !isSidePanel ? summaries[activeTab as SummaryMode] : undefined
  const isStreaming = !isSidePanel ? (streaming[activeTab as SummaryMode] ?? false) : false

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex flex-wrap gap-1 rounded-md bg-muted p-1">
        {allTabs.map((tab) => (
          <button
            key={tab.mode}
            onClick={() => setActiveTab(tab.mode)}
            className={cn(
              "flex-1 rounded py-1.5 text-xs font-medium transition-colors",
              activeTab === tab.mode
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto">
        {summaryError && activeTab !== "references" && activeTab !== "notes" && (
          <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            {summaryError}
          </div>
        )}
        {activeTab === "notes" ? (
          <NotesReaderPanel documentId={documentId} activeSectionId={activeSectionId ?? null} onScrollToSection={onScrollToSection} onNoteCountKnown={handleNoteCountKnown} />
        ) : activeTab === "references" ? (
          <ReferencesPanel documentId={documentId} />
        ) : activeTab === "glossary" ? (
          <GlossaryPanel documentId={documentId} onScrollToSection={onScrollToSection} />
        ) : cacheLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 size={14} className="animate-spin" />
            Loading...
          </div>
        ) : isStreaming && !currentSummary ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 size={14} className="animate-spin" />
            Summarizing...
          </div>
        ) : currentSummary ? (
          <div className="space-y-2">
            <div>
              <MarkdownRenderer>{currentSummary}</MarkdownRenderer>
              {isStreaming && <span className="animate-pulse text-foreground">▍</span>}
            </div>
            {!isStreaming && (
              <button
                title="Regenerate summary (uses LLM -- may take a moment)"
                onClick={() => void generateSummary(activeTab as SummaryMode, true)}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
              >
                <RefreshCw size={12} />
                Regenerate
              </button>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted-foreground">No summary yet.</p>
            <button
              onClick={() => void generateSummary(activeTab as SummaryMode)}
              className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
              Generate Summary
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
