import { useQuery } from "@tanstack/react-query"
import { ArrowLeft, Loader2, RefreshCw } from "lucide-react"
import { useState } from "react"
import { cn } from "@/lib/utils"
import { CONTENT_TYPE_ICONS, formatWordCount, relativeDate } from "@/components/library/utils"
import type { ContentType } from "@/components/library/types"
import type { DocumentDetail, SummaryMode, SummaryTabDef } from "./types"
import { CONVERSATION_TAB, SUMMARY_TABS } from "./types"

const API_BASE = "http://localhost:8000"

async function fetchDocument(id: string): Promise<DocumentDetail> {
  const res = await fetch(`${API_BASE}/documents/${id}`)
  if (!res.ok) throw new Error("Failed to fetch document")
  return res.json() as Promise<DocumentDetail>
}

type SummaryMap = Partial<Record<SummaryMode, string>>
type StreamingMap = Partial<Record<SummaryMode, boolean>>

interface SummaryPanelProps {
  documentId: string
  contentType: string
}

function SummaryPanel({ documentId, contentType }: SummaryPanelProps) {
  const tabs: SummaryTabDef[] =
    contentType === "conversation" ? [...SUMMARY_TABS, CONVERSATION_TAB] : SUMMARY_TABS
  const [activeTab, setActiveTab] = useState<SummaryMode>(tabs[0].mode)
  const [summaries, setSummaries] = useState<SummaryMap>({})
  const [streaming, setStreaming] = useState<StreamingMap>({})

  async function generateSummary(mode: SummaryMode) {
    setStreaming((s) => ({ ...s, [mode]: true }))
    setSummaries((s) => ({ ...s, [mode]: "" }))
    try {
      const res = await fetch(`${API_BASE}/summarize/${documentId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, model: null }),
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
    }
  }

  const currentSummary = summaries[activeTab]
  const isStreaming = streaming[activeTab] ?? false

  return (
    <div className="flex h-full flex-col">
      {/* Tabs */}
      <div className="mb-4 flex gap-1 rounded-md bg-muted p-1">
        {tabs.map((tab) => (
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

      {/* Content area */}
      <div className="flex-1 overflow-auto">
        {isStreaming && !currentSummary ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 size={14} className="animate-spin" />
            Summarizing...
          </div>
        ) : currentSummary ? (
          <div className="space-y-2">
            <pre className="whitespace-pre-wrap font-sans text-sm text-foreground leading-relaxed">
              {currentSummary}
              {isStreaming && <span className="animate-pulse">▍</span>}
            </pre>
            {!isStreaming && (
              <button
                onClick={() => void generateSummary(activeTab)}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
              >
                <RefreshCw size={12} />
                Regenerate
              </button>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted-foreground">No summary generated yet.</p>
            <button
              onClick={() => void generateSummary(activeTab)}
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

interface DocumentReaderProps {
  documentId: string
  onBack: () => void
}

export function DocumentReader({ documentId, onBack }: DocumentReaderProps) {
  const { data: doc, isLoading } = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => fetchDocument(documentId),
  })

  if (isLoading) {
    return (
      <div className="flex h-full gap-6 p-6">
        <div className="flex w-3/5 flex-col gap-4">
          <div className="h-8 animate-pulse rounded bg-muted" />
          <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
          <div className="flex-1 space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-14 animate-pulse rounded bg-muted" />
            ))}
          </div>
        </div>
        <div className="w-2/5">
          <div className="h-32 animate-pulse rounded bg-muted" />
        </div>
      </div>
    )
  }

  if (!doc) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-muted-foreground">Document not found.</p>
      </div>
    )
  }

  const Icon = CONTENT_TYPE_ICONS[doc.content_type as ContentType] ?? CONTENT_TYPE_ICONS.notes

  return (
    <div className="flex h-full flex-col">
      {/* Back button */}
      <div className="border-b border-border px-6 py-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft size={14} />
          Back to library
        </button>
      </div>

      {/* Two-panel layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left panel — 60% */}
        <div className="flex w-3/5 flex-col overflow-hidden border-r border-border">
          {/* Document header */}
          <div className="px-6 py-4">
            <h1 className="text-lg font-bold text-foreground">{doc.title}</h1>
            <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
              <Icon size={14} />
              <span className="capitalize">{doc.content_type}</span>
              <span>·</span>
              <span>{formatWordCount(doc.word_count)}</span>
              <span>·</span>
              <span>{relativeDate(doc.created_at)}</span>
            </div>
          </div>

          {/* Section list */}
          <div className="flex-1 overflow-auto px-6 pb-6">
            {doc.sections.length === 0 ? (
              <p className="text-sm text-muted-foreground">No sections detected.</p>
            ) : (
              <ul className="space-y-3">
                {doc.sections.map((section) => (
                  <li
                    key={section.id}
                    className="rounded-md border border-border p-3"
                  >
                    <p
                      className="text-sm font-semibold text-foreground"
                      style={{ paddingLeft: `${(section.level - 1) * 12}px` }}
                    >
                      {section.heading || "(Untitled section)"}
                    </p>
                    {section.preview && (
                      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                        {section.preview}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* Right panel — 40%, sticky */}
        <div className="w-2/5 overflow-auto p-6">
          <h2 className="mb-4 text-sm font-semibold text-foreground">Summary</h2>
          <SummaryPanel documentId={documentId} contentType={doc.content_type} />
        </div>
      </div>
    </div>
  )
}
