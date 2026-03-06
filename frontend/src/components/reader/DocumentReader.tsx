import { useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Loader2, RefreshCw, StickyNote, Check, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"
import { CONTENT_TYPE_ICONS, formatWordCount, relativeDate } from "@/components/library/utils"
import type { ContentType } from "@/components/library/types"
import { ExplanationSheet } from "@/components/ExplanationSheet"
import { FloatingToolbar } from "@/components/FloatingToolbar"
import type { ExplainMode } from "@/components/FloatingToolbar"
import type { DocumentDetail, SummaryMode, SummaryTabDef } from "./types"
import { CONVERSATION_TAB, SUMMARY_TABS } from "./types"
import { IngestionHealthPanel } from "@/components/library/IngestionHealthPanel"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"

const API_BASE = "http://localhost:8000"

async function fetchDocument(id: string): Promise<DocumentDetail> {
  const res = await fetch(`${API_BASE}/documents/${id}`)
  if (!res.ok) throw new Error("Failed to fetch document")
  return res.json() as Promise<DocumentDetail>
}

// ---------------------------------------------------------------------------
// Note API
// ---------------------------------------------------------------------------

async function createNote(data: {
  document_id: string
  content: string
  tags: string[]
  group_name: string | null
}): Promise<void> {
  await fetch(`${API_BASE}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
}

// ---------------------------------------------------------------------------
// NoteEditor (inline below a section)
// ---------------------------------------------------------------------------

interface NoteEditorProps {
  documentId: string
  onSaved: () => void
  onCancel: () => void
}

function NoteEditor({ documentId, onSaved, onCancel }: NoteEditorProps) {
  const [content, setContent] = useState("")
  const [tagInput, setTagInput] = useState("")
  const [tags, setTags] = useState<string[]>([])
  const [saving, setSaving] = useState(false)

  function addTag(input: string) {
    const t = input.trim()
    if (t && !tags.includes(t)) setTags((prev) => [...prev, t])
    setTagInput("")
  }

  async function handleSave() {
    if (!content.trim()) return
    setSaving(true)
    try {
      await createNote({ document_id: documentId, content, tags, group_name: null })
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-2 flex flex-col gap-2 rounded-md border border-primary/40 bg-background p-2">
      <textarea
        autoFocus
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Write a note..."
        className="min-h-[72px] w-full resize-none bg-transparent text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
      />
      {/* Tag input */}
      <div className="flex flex-wrap items-center gap-1">
        {tags.map((t) => (
          <span
            key={t}
            className="flex items-center gap-0.5 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
          >
            {t}
            <button onClick={() => setTags((prev) => prev.filter((x) => x !== t))}>
              <X size={9} />
            </button>
          </span>
        ))}
        <input
          value={tagInput}
          onChange={(e) => setTagInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault()
              addTag(tagInput)
            }
          }}
          onBlur={() => { if (tagInput.trim()) addTag(tagInput) }}
          placeholder="Add tag, press Enter"
          className="flex-1 bg-transparent text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
        />
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => void handleSave()}
          disabled={saving || !content.trim()}
          className="flex items-center gap-1 rounded bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          <Check size={11} />
          {saving ? "Saving..." : "Save"}
        </button>
        <button
          onClick={onCancel}
          className="rounded border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

type SummaryMap = Partial<Record<SummaryMode, string>>
type StreamingMap = Partial<Record<SummaryMode, boolean>>

// ---------------------------------------------------------------------------
// Glossary tab
// ---------------------------------------------------------------------------

interface GlossaryTerm {
  term: string
  definition: string
  first_mention_page: number
}

interface GlossaryPanelProps {
  documentId: string
}

function GlossaryPanel({ documentId }: GlossaryPanelProps) {
  const [terms, setTerms] = useState<GlossaryTerm[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState("")

  async function loadGlossary() {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/explain/glossary/${documentId}`, { method: "POST" })
      if (res.ok) {
        const data = (await res.json()) as GlossaryTerm[]
        setTerms(data)
      }
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  const filtered = (terms ?? []).filter((t) =>
    t.term.toLowerCase().includes(filter.toLowerCase()),
  )

  if (terms === null) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          Extract domain-specific terms from this document.
        </p>
        <button
          onClick={() => void loadGlossary()}
          disabled={loading}
          className="flex items-center gap-1.5 self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
        >
          {loading && <Loader2 size={14} className="animate-spin" />}
          {loading ? "Extracting..." : "Generate Glossary"}
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter terms..."
        className="rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
      />
      {filtered.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {filter ? "No matching terms." : "No terms extracted."}
        </p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="pb-1.5 pr-3 font-medium">Term</th>
              <th className="pb-1.5 pr-3 font-medium">Definition</th>
              <th className="pb-1.5 font-medium">Page</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {filtered.map((t, i) => (
              <tr key={i}>
                <td className="py-1.5 pr-3 font-medium text-foreground align-top">{t.term}</td>
                <td className="py-1.5 pr-3 text-foreground/80 align-top">{t.definition}</td>
                <td className="py-1.5 text-muted-foreground align-top">{t.first_mention_page > 0 ? `p.${t.first_mention_page}` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Summary + Glossary panel (right side)
// ---------------------------------------------------------------------------

type PanelTab = SummaryMode | "glossary"

interface SummaryPanelProps {
  documentId: string
  contentType: string
}

function SummaryPanel({ documentId, contentType }: SummaryPanelProps) {
  const summaryTabs: SummaryTabDef[] =
    contentType === "conversation" ? [...SUMMARY_TABS, CONVERSATION_TAB] : SUMMARY_TABS
  const allTabs = [...summaryTabs.map((t) => ({ mode: t.mode as PanelTab, label: t.label })), { mode: "glossary" as PanelTab, label: "Glossary" }]

  const [activeTab, setActiveTab] = useState<PanelTab>(allTabs[0].mode)
  const [summaries, setSummaries] = useState<SummaryMap>({})
  const [streaming, setStreaming] = useState<StreamingMap>({})
  const [summaryError, setSummaryError] = useState<string | null>(null)
  const [cacheLoading, setCacheLoading] = useState(true)

  // Load pre-generated summaries from DB on mount — no LLM call needed
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
        // cache unavailable — user can still generate manually
      } finally {
        if (!cancelled) setCacheLoading(false)
      }
    }
    void loadCached()
    return () => { cancelled = true }
  }, [documentId])

  async function generateSummary(mode: SummaryMode, forceRefresh = false) {
    setSummaryError(null)

    // Check cache first (skipped when forceRefresh=true)
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
        // cache check failed — fall through to streaming
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

  const currentSummary = activeTab !== "glossary" ? summaries[activeTab as SummaryMode] : undefined
  const isStreaming = activeTab !== "glossary" ? (streaming[activeTab as SummaryMode] ?? false) : false

  return (
    <div className="flex h-full flex-col">
      {/* Tabs */}
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

      {/* Content area */}
      <div className="flex-1 overflow-auto">
        {summaryError && (
          <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            {summaryError}
          </div>
        )}
        {activeTab === "glossary" ? (
          <GlossaryPanel documentId={documentId} />
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
                title="Regenerate summary (uses LLM — may take a moment)"
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

// ---------------------------------------------------------------------------
// DocumentReader
// ---------------------------------------------------------------------------

interface DocumentReaderProps {
  documentId: string
  onBack: () => void
}

export function DocumentReader({ documentId, onBack }: DocumentReaderProps) {
  const qc = useQueryClient()
  const { data: doc, isLoading } = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => fetchDocument(documentId),
  })
  const sectionListRef = useRef<HTMLDivElement>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [sheetText, setSheetText] = useState("")
  const [sheetMode, setSheetMode] = useState<ExplainMode>("plain")
  const [openNoteEditor, setOpenNoteEditor] = useState<string | null>(null) // section id
  const [notedSections, setNotedSections] = useState<Set<string>>(new Set())

  function handleExplain(text: string, mode: ExplainMode) {
    setSheetText(text)
    setSheetMode(mode)
    setSheetOpen(true)
  }

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
            <div className="mt-3">
              <IngestionHealthPanel documentId={documentId} stage={doc.stage} />
            </div>
          </div>

          {/* Section list — relative for FloatingToolbar positioning */}
          <div ref={sectionListRef} className="relative flex-1 overflow-auto px-6 pb-6">
            <FloatingToolbar containerRef={sectionListRef} onExplain={handleExplain} />
            {doc.sections.length === 0 ? (
              <p className="text-sm text-muted-foreground">No sections detected.</p>
            ) : (
              <ul className="space-y-3">
                {doc.sections.map((section) => {
                  const hasNote = notedSections.has(section.id)
                  const editorOpen = openNoteEditor === section.id
                  return (
                    <li
                      key={section.id}
                      className="rounded-md border border-border p-3"
                    >
                      <div className="flex items-start gap-1">
                        <p
                          className="flex-1 text-sm font-semibold text-foreground"
                          style={{ paddingLeft: `${(section.level - 1) * 12}px` }}
                        >
                          {section.heading || "(Untitled section)"}
                        </p>
                        {hasNote && (
                          <span title="Has note" className="mt-0.5 shrink-0 text-primary">
                            <StickyNote size={12} />
                          </span>
                        )}
                        <button
                          onClick={() =>
                            setOpenNoteEditor(editorOpen ? null : section.id)
                          }
                          title="Add note"
                          className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground"
                        >
                          <StickyNote size={12} />
                        </button>
                      </div>
                      {section.preview && (
                        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                          {section.preview}
                        </p>
                      )}
                      {editorOpen && (
                        <NoteEditor
                          documentId={documentId}
                          onSaved={() => {
                            setNotedSections((prev) => new Set([...prev, section.id]))
                            setOpenNoteEditor(null)
                            void qc.invalidateQueries({ queryKey: ["notes-for-doc", documentId] })
                          }}
                          onCancel={() => setOpenNoteEditor(null)}
                        />
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        </div>

        {/* Right panel — 40%, sticky */}
        <div className="w-2/5 overflow-auto p-6">
          <SummaryPanel documentId={documentId} contentType={doc.content_type} />
        </div>
      </div>

      {/* Explanation sheet */}
      <ExplanationSheet
        open={sheetOpen}
        text={sheetText}
        documentId={documentId}
        mode={sheetMode}
        onClose={() => setSheetOpen(false)}
      />
    </div>
  )
}
