import { useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, BookOpen, Loader2, RefreshCw, StickyNote, Check, X, Trash2, Play, Pause, Terminal, Brain, Search, ChevronUp, ChevronDown, Highlighter, ChevronRight, GitCompareArrows } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { CONTENT_TYPE_ICONS, formatWordCount, isYouTubeDoc, relativeDate } from "@/components/library/utils"
import type { ContentType } from "@/components/library/types"
import { ExplanationSheet } from "@/components/ExplanationSheet"
import type { ExplainMode } from "@/components/FloatingToolbar"
import type { AnnotationItem, DocumentDetail, SectionItem, SummaryMode, SummaryTabDef } from "./types"
import { CONVERSATION_TAB, SUMMARY_TABS } from "./types"
import { IngestionHealthPanel } from "@/components/library/IngestionHealthPanel"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { SelectionActionBar } from "./SelectionActionBar"
import type { SourceRef } from "./SelectionActionBar"
import { NoteCreationDialog } from "./NoteCreationDialog"
import { NoteEditorDialog, type Note } from "@/components/NoteEditorDialog"
import { DocumentFlashcardDialog } from "./DocumentFlashcardDialog"
import { FeynmanDialog } from "./FeynmanDialog"
import { PDFViewer, type PDFViewerHandle } from "./PDFViewer"
import { EPUBViewer } from "./EPUBViewer"
import { ReadView } from "./ReadView"
import { resolveFromDom, resolvePdfFallback } from "./resolveSourceRefUtils"
import { YouTubeTranscriptView } from "./YouTubeTranscriptView"
import { NotesReaderPanel } from "./NotesReaderPanel"
import { ReferencesPanel } from "./ReferencesPanel"
import { Skeleton } from "@/components/ui/skeleton"
import { useAppStore } from "@/store"

import { API_BASE } from "@/lib/config"
import { useDebounce } from "@/hooks/useDebounce"

// ---------------------------------------------------------------------------
// FSRS fragility heatmap (S116)
// ---------------------------------------------------------------------------

interface SectionHeatmapItem {
  section_id: string
  fragility_score: number | null
  due_card_count: number
  avg_retention_pct: number | null
}

function fragilityBorderClass(score: number | null): string {
  if (score === null) return ""
  if (score <= 0.3) return "border-l-4 border-l-green-500"
  if (score <= 0.6) return "border-l-4 border-l-yellow-500"
  return "border-l-4 border-l-red-500"
}

const ADMONITION_STYLES: Record<string, string> = {
  note:      "border-l-4 border-l-blue-500 bg-blue-50/40",
  warning:   "border-l-4 border-l-red-500 bg-red-50/40",
  tip:       "border-l-4 border-l-green-500 bg-green-50/40",
  caution:   "border-l-4 border-l-orange-500 bg-orange-50/40",
  important: "border-l-4 border-l-purple-500 bg-purple-50/40",
}

const ADMONITION_LABEL_COLORS: Record<string, string> = {
  note:      "#3b82f6",
  warning:   "#ef4444",
  tip:       "#22c55e",
  caution:   "#f97316",
  important: "#a855f7",
}

function admonitionClass(type: string | null): string {
  if (!type) return ""
  return ADMONITION_STYLES[type] ?? ""
}

function buildYouTubeTimestampUrl(sourceUrl: string, seconds: number): string {
  const t = Math.floor(seconds)
  return sourceUrl.includes("?") ? `${sourceUrl}&t=${t}` : `${sourceUrl}?t=${t}`
}

// ---------------------------------------------------------------------------

async function fetchDocument(id: string): Promise<DocumentDetail> {
  const res = await fetch(`${API_BASE}/documents/${id}`)
  if (!res.ok) throw new Error("Failed to fetch document")
  return res.json() as Promise<DocumentDetail>
}

// ---------------------------------------------------------------------------
// Note API
// ---------------------------------------------------------------------------

// Minimal note shape used for the section indicator (section_id only)
interface NoteEntry {
  id: string
  section_id: string | null
}

async function createNote(data: {
  document_id: string
  section_id: string | undefined
  content: string
  tags: string[]
  group_name: string | null
}): Promise<void> {
  const res = await fetch(`${API_BASE}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`Failed to create note: ${res.status}`)
}

// ---------------------------------------------------------------------------
// NoteEditor (inline below a section)
// ---------------------------------------------------------------------------

interface NoteEditorProps {
  documentId: string
  sectionId: string
  onSaved: () => void
  onCancel: () => void
}

function NoteEditor({ documentId, sectionId, onSaved, onCancel }: NoteEditorProps) {
  const [content, setContent] = useState("")
  const [tagInput, setTagInput] = useState("")
  const [tags, setTags] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  function addTag(input: string) {
    const t = input.trim()
    if (t && !tags.includes(t)) setTags((prev) => [...prev, t])
    setTagInput("")
  }

  async function handleSave() {
    if (!content.trim()) return
    setSaving(true)
    setSaveError(null)
    try {
      await createNote({ document_id: documentId, section_id: sectionId, content, tags, group_name: null })
      onSaved()
    } catch {
      setSaveError("Failed to save note. Please try again.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-2 flex flex-col gap-2 rounded-md border border-primary/40 bg-background p-2">
      {saveError && (
        <p className="text-xs text-destructive">{saveError}</p>
      )}
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
  id: string
  term: string
  definition: string
  first_mention_section_id: string | null
  category: string | null
  created_at: string | null
  updated_at: string | null
}

const CATEGORY_COLORS: Record<string, string> = {
  character: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  place: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  concept: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
  technical: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
  event: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  general: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
}

type GlossarySortKey = "term" | "category"

interface GlossaryPanelProps {
  documentId: string
  onScrollToSection?: (sectionId: string) => void
}

function GlossaryPanel({ documentId, onScrollToSection }: GlossaryPanelProps) {
  const [terms, setTerms] = useState<GlossaryTerm[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [initialLoading, setInitialLoading] = useState(true)
  const [filter, setFilter] = useState("")
  const [sortKey, setSortKey] = useState<GlossarySortKey>("term")
  const [error, setError] = useState("")

  // Load cached terms on mount
  useEffect(() => {
    let cancelled = false
    async function fetchCached() {
      try {
        const res = await fetch(`${API_BASE}/explain/glossary/${documentId}/cached`)
        if (res.ok) {
          const data = (await res.json()) as GlossaryTerm[]
          if (!cancelled) setTerms(data.length > 0 ? data : null)
        }
      } catch {
        // ignore fetch error on initial load
      } finally {
        if (!cancelled) setInitialLoading(false)
      }
    }
    void fetchCached()
    return () => { cancelled = true }
  }, [documentId])

  async function generateGlossary() {
    setLoading(true)
    setError("")
    try {
      const res = await fetch(`${API_BASE}/explain/glossary/${documentId}`, { method: "POST" })
      if (res.ok) {
        const data = (await res.json()) as GlossaryTerm[]
        setTerms(data)
      } else {
        const body = await res.json().catch(() => ({ detail: "Unknown error" })) as { detail?: string }
        if (res.status === 503) {
          setError("Ollama unavailable -- start it to generate glossary")
        } else if (res.status === 422) {
          setError(body.detail ?? "Glossary generation failed -- try again")
        } else {
          setError(body.detail ?? `Error ${res.status}`)
        }
      }
    } catch {
      setError("Network error -- check your connection")
    } finally {
      setLoading(false)
    }
  }

  async function deleteTerm(termId: string) {
    try {
      const res = await fetch(`${API_BASE}/explain/glossary/${documentId}/terms/${termId}`, { method: "DELETE" })
      if (res.ok || res.status === 204) {
        setTerms((prev) => prev ? prev.filter((t) => t.id !== termId) : prev)
      }
    } catch {
      // ignore
    }
  }

  const filterLower = filter.toLowerCase()
  const filtered = (terms ?? [])
    .filter((t) =>
      t.term.toLowerCase().includes(filterLower) ||
      t.definition.toLowerCase().includes(filterLower),
    )
    .sort((a, b) => {
      if (sortKey === "category") {
        return (a.category ?? "general").localeCompare(b.category ?? "general") || a.term.localeCompare(b.term)
      }
      return a.term.localeCompare(b.term)
    })

  if (initialLoading) {
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    )
  }

  const hasTerms = terms !== null && terms.length > 0

  if (!hasTerms) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          Extract domain-specific terms from this document.
        </p>
        <button
          onClick={() => void generateGlossary()}
          disabled={loading}
          className="flex items-center gap-1.5 self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
        >
          {loading && <Loader2 size={14} className="animate-spin" />}
          {loading ? "Extracting..." : "Generate Glossary"}
        </button>
        {error && <p className="text-sm text-red-500">{error}</p>}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Search terms and definitions..."
          className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <button
          onClick={() => void generateGlossary()}
          disabled={loading}
          title="Regenerate glossary"
          className="flex items-center gap-1 rounded-md border border-border px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
        >
          {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          Regenerate
        </button>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>Sort:</span>
        <button
          onClick={() => setSortKey("term")}
          className={cn("px-1.5 py-0.5 rounded", sortKey === "term" ? "bg-primary text-primary-foreground" : "hover:bg-muted")}
        >
          Term
        </button>
        <button
          onClick={() => setSortKey("category")}
          className={cn("px-1.5 py-0.5 rounded", sortKey === "category" ? "bg-primary text-primary-foreground" : "hover:bg-muted")}
        >
          Category
        </button>
      </div>
      {error && <p className="text-sm text-red-500">{error}</p>}
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
              <th className="pb-1.5 pr-3 font-medium">Category</th>
              <th className="pb-1.5 font-medium">Section</th>
              <th className="pb-1.5 w-6"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {filtered.map((t) => (
              <tr key={t.id}>
                <td className="py-1.5 pr-3 font-medium text-foreground align-top">{t.term}</td>
                <td className="py-1.5 pr-3 text-foreground/80 align-top">{t.definition}</td>
                <td className="py-1.5 pr-3 align-top">
                  {t.category && (
                    <span className={cn("inline-block rounded px-1.5 py-0.5 text-[10px] font-medium", CATEGORY_COLORS[t.category] ?? CATEGORY_COLORS.general)}>
                      {t.category}
                    </span>
                  )}
                </td>
                <td className="py-1.5 pr-1 align-top">
                  {t.first_mention_section_id && onScrollToSection ? (
                    <button
                      onClick={() => onScrollToSection(t.first_mention_section_id!)}
                      className="text-primary hover:underline text-[10px]"
                    >
                      Go
                    </button>
                  ) : (
                    <span className="text-muted-foreground">--</span>
                  )}
                </td>
                <td className="py-1.5 align-top">
                  <button
                    onClick={() => void deleteTerm(t.id)}
                    className="text-muted-foreground hover:text-red-500 transition-colors sm:opacity-0 sm:group-hover:opacity-100"
                    title="Remove term"
                  >
                    <Trash2 size={12} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Chapter Goals panel (right side, tech books only)
// ---------------------------------------------------------------------------

interface LearningObjective {
  id: string
  section_id: string
  text: string
  covered: boolean
}

interface ChapterProgressRingProps {
  pct: number
  size?: number
}

function ChapterProgressRing({ pct, size = 12 }: ChapterProgressRingProps) {
  const r = (size - 2) / 2
  const circ = 2 * Math.PI * r
  const dashOffset = circ - (pct / 100) * circ
  return (
    <svg width={size} height={size} className="shrink-0" aria-label={`${Math.round(pct)}% covered`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={1.5} className="text-muted/30" />
      <circle
        cx={size / 2} cy={size / 2} r={r}
        fill="none" stroke="currentColor" strokeWidth={1.5}
        strokeDasharray={circ} strokeDashoffset={dashOffset}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        className="text-primary"
      />
    </svg>
  )
}

interface ChapterGoalsPanelProps {
  documentId: string
  sectionId?: string | null
  onStudyClick: (sectionId: string) => void
}

function ChapterGoalsPanel({ documentId, sectionId, onStudyClick }: ChapterGoalsPanelProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["objectives", documentId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/documents/${documentId}/objectives`)
      if (!res.ok) throw new Error("Failed to fetch objectives")
      return res.json() as Promise<{ objectives: LearningObjective[] }>
    },
    staleTime: 300_000,
  })

  if (isLoading) {
    return (
      <div className="mb-4 flex flex-col gap-1.5 py-2">
        {[1, 2, 3].map((i) => <Skeleton key={i} className="h-4 w-full" />)}
      </div>
    )
  }

  if (isError) {
    return <p className="mb-4 text-xs text-destructive">Could not load chapter goals.</p>
  }

  if (!data || data.objectives.length === 0) {
    return null
  }

  const visibleObjectives = sectionId
    ? data.objectives.filter((o) => o.section_id === sectionId)
    : data.objectives

  if (visibleObjectives.length === 0) {
    return (
      <div className="mb-4 rounded-lg border border-border bg-card p-4">
        <h3 className="mb-1 text-sm font-semibold text-foreground">Chapter Goals</h3>
        <p className="text-xs text-muted-foreground">No learning objectives for this section.</p>
      </div>
    )
  }

  return (
    <div className="mb-4 rounded-lg border border-border bg-card p-4">
      <h3 className="mb-2 text-sm font-semibold text-foreground">Chapter Goals</h3>
      <ul className="space-y-1.5">
        {visibleObjectives.map((obj) => (
          <li key={obj.id} className="flex items-start gap-2 text-xs text-foreground/80">
            <input
              type="checkbox"
              checked={obj.covered}
              readOnly
              className="mt-0.5 shrink-0 accent-primary"
            />
            <span className="flex-1">{obj.text}</span>
            {!obj.covered && (
              <button
                onClick={() => onStudyClick(obj.section_id)}
                className="ml-auto shrink-0 rounded bg-primary px-2 py-0.5 text-xs text-primary-foreground hover:bg-primary/90"
              >
                Study
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Summary + Glossary panel (right side)
// ---------------------------------------------------------------------------

type PanelTab = SummaryMode | "glossary" | "references" | "notes"

interface SummaryPanelProps {
  documentId: string
  contentType: string
  activeSectionId?: string | null
  onScrollToSection?: (sectionId: string) => void
  onNoteCountKnown: (count: number) => void
}

function SummaryPanel({ documentId, contentType, activeSectionId, onScrollToSection, onNoteCountKnown }: SummaryPanelProps) {
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

  // AC5: switch default tab to Key Points if no notes exist
  const handleNoteCountKnown = useCallback((count: number) => {
    onNoteCountKnown(count)
    if (!defaultTabResolved.current) {
      defaultTabResolved.current = true
      if (count === 0) {
        setActiveTab("executive")
      }
    }
  }, [onNoteCountKnown])

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

  const isSidePanel = activeTab === "glossary" || activeTab === "references" || activeTab === "notes"
  const currentSummary = !isSidePanel ? summaries[activeTab as SummaryMode] : undefined
  const isStreaming = !isSidePanel ? (streaming[activeTab as SummaryMode] ?? false) : false

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
// Annotation highlight reconstruction (S111)
// ---------------------------------------------------------------------------

const COLOR_CLASSES: Record<string, string> = {
  yellow: "bg-yellow-200 dark:bg-yellow-900/50",
  green: "bg-green-200 dark:bg-green-900/50",
  blue: "bg-blue-200 dark:bg-blue-900/50",
  pink: "bg-pink-200 dark:bg-pink-900/50",
}

interface SectionPreviewProps {
  preview: string
  annotations: AnnotationItem[]
  sectionId: string
  searchSnippet?: string
}

function SectionPreviewWithHighlights({ preview, annotations, sectionId, searchSnippet }: SectionPreviewProps) {
  // S151: render FTS5 snippet with <mark> tags when a search hit exists for this section
  if (searchSnippet) {
    return (
      <p
        className="mt-1 line-clamp-2 text-xs text-muted-foreground section-preview"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: sanitizeSnippet(searchSnippet) }}
      />
    )
  }
  const sectionAnnotations = annotations
    .filter((a) => a.section_id === sectionId)
    .sort((a, b) => a.start_offset - b.start_offset)

  if (sectionAnnotations.length === 0) {
    return (
      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground section-preview">{preview}</p>
    )
  }

  // Build segments — skip overlapping annotations (keep first)
  const segments: { text: string; annotation: AnnotationItem | null }[] = []
  let cursor = 0
  for (const ann of sectionAnnotations) {
    const start = ann.start_offset
    const end = ann.end_offset
    // Validate offsets and skip invalid / overlapping annotations
    if (start < cursor || end <= start || end > preview.length) continue
    const highlightText = preview.slice(start, end)
    // Verify text matches to avoid phantom highlights from stale data
    if (!ann.selected_text.startsWith(highlightText.slice(0, 10))) continue
    if (start > cursor) segments.push({ text: preview.slice(cursor, start), annotation: null })
    segments.push({ text: highlightText, annotation: ann })
    cursor = end
  }
  if (cursor < preview.length) segments.push({ text: preview.slice(cursor), annotation: null })

  return (
    <p className="mt-1 line-clamp-2 text-xs text-muted-foreground section-preview">
      {segments.map((seg, i) =>
        seg.annotation ? (
          <mark
            key={i}
            data-annotation-id={seg.annotation.id}
            className={cn("rounded-sm", COLOR_CLASSES[seg.annotation.color] ?? COLOR_CLASSES.yellow)}
            title={seg.annotation.note_text ?? undefined}
          >
            {seg.text}
          </mark>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </p>
  )
}

// ---------------------------------------------------------------------------
// Highlights panel (left panel tab)
// ---------------------------------------------------------------------------

interface HighlightsPanelProps {
  annotations: AnnotationItem[]
  loading: boolean
  error: boolean
  onDelete: (id: string) => void
}

// @ts-expect-error -- HighlightsPanel is defined for upcoming highlights sidebar; not yet wired
function HighlightsPanel({ annotations, loading, error, onDelete }: HighlightsPanelProps) {
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  async function handleConfirmDelete(id: string) {
    setDeleting(true)
    try {
      await fetch(`${API_BASE}/annotations/${id}`, { method: "DELETE" })
      onDelete(id)
      setConfirmDelete(null)
    } catch {
      // keep confirm open so user can retry
    } finally {
      setDeleting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col gap-2 px-6 py-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded-md bg-muted" />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="px-6 py-3">
        <p className="text-xs text-destructive">Could not load highlights.</p>
      </div>
    )
  }

  if (annotations.length === 0) {
    return (
      <div className="px-6 py-3">
        <p className="text-xs text-muted-foreground">
          No highlights yet. Select text and click Highlight.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 px-6 py-3">
      {annotations.map((ann) => (
        <div key={ann.id} className="rounded-md border border-border p-2">
          {confirmDelete === ann.id ? (
            <div className="flex flex-col gap-2">
              <p className="text-xs text-foreground">Delete this highlight?</p>
              <div className="flex gap-2">
                <button
                  onClick={() => void handleConfirmDelete(ann.id)}
                  disabled={deleting}
                  className="rounded bg-destructive px-2 py-0.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
                >
                  {deleting ? "Deleting..." : "Yes"}
                </button>
                <button
                  onClick={() => setConfirmDelete(null)}
                  disabled={deleting}
                  className="rounded border border-border px-2 py-0.5 text-xs hover:bg-accent disabled:opacity-50"
                >
                  No
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-start gap-2">
              <span
                className={cn(
                  "mt-0.5 h-2 w-2 shrink-0 rounded-full",
                  COLOR_CLASSES[ann.color] ?? COLOR_CLASSES.yellow,
                )}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs text-foreground" title={ann.selected_text}>
                  {ann.selected_text.length > 60
                    ? `${ann.selected_text.slice(0, 60)}...`
                    : ann.selected_text}
                </p>
                {ann.note_text && (
                  <p className="mt-0.5 text-xs text-muted-foreground">{ann.note_text}</p>
                )}
              </div>
              <button
                onClick={() => setConfirmDelete(ann.id)}
                title="Delete highlight"
                className="shrink-0 text-muted-foreground hover:text-destructive"
              >
                <Trash2 size={12} />
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Reading progress tracking (S110)
// ---------------------------------------------------------------------------

async function postReadingProgress(documentId: string, sectionId: string): Promise<void> {
  try {
    await fetch(`${API_BASE}/reading/progress`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: documentId, section_id: sectionId }),
    })
  } catch {
    // Best-effort: network errors must never interrupt reading
  }
}

function useReadingProgress(documentId: string, sectionCount: number) {
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  // Track whether any progress was posted so we can invalidate the library
  // query on unmount and keep the progress bar in sync within the same session.
  const progressPosted = useRef(false)
  const qc = useQueryClient()

  useEffect(() => {
    if (sectionCount === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const sectionId = (entry.target as HTMLElement).dataset["sectionId"]
          if (!sectionId) continue

          if (entry.isIntersecting) {
            if (!timers.current.has(sectionId)) {
              const t = setTimeout(() => {
                timers.current.delete(sectionId)
                progressPosted.current = true
                void postReadingProgress(documentId, sectionId)
              }, 3000)
              timers.current.set(sectionId, t)
            }
          } else {
            const t = timers.current.get(sectionId)
            if (t !== undefined) {
              clearTimeout(t)
              timers.current.delete(sectionId)
            }
          }
        }
      },
      { threshold: 0.5 },
    )

    const elements = document.querySelectorAll("[data-section-id]")
    for (const el of elements) observer.observe(el)

    return () => {
      observer.disconnect()
      for (const t of timers.current.values()) clearTimeout(t)
      timers.current.clear()
      // Invalidate the library query so progress bars reflect this session.
      if (progressPosted.current) {
        void qc.invalidateQueries({ queryKey: ["documents"] })
        progressPosted.current = false
      }
    }
  }, [documentId, sectionCount, qc])
}

// ---------------------------------------------------------------------------
// Audio mini-player (S120)
// ---------------------------------------------------------------------------

/**
 * Parse the start time (in seconds) from an audio section heading.
 * Heading format: "Segment N (XYZs-ABCs)" — produced by _chunk_audio in ingestion.py.
 * Returns null if the heading does not match the expected pattern.
 */
function parseAudioStartTime(heading: string): number | null {
  const m = heading.match(/\((\d+(?:\.\d+)?)s-/)
  if (!m) return null
  return parseFloat(m[1])
}

function formatMmSs(seconds: number): string {
  const s = Math.floor(seconds)
  const mm = Math.floor(s / 60).toString().padStart(2, "0")
  const ss = (s % 60).toString().padStart(2, "0")
  return `${mm}:${ss}`
}

interface AudioMiniPlayerProps {
  audioRef: React.RefObject<HTMLAudioElement | null>
  audioUrl: string
  playing: boolean
  currentTime: number
  duration: number
  onPlayPause: () => void
  onSeek: (t: number) => void
  onTimeUpdate: () => void
  onLoadedMetadata: () => void
  onEnded: () => void
}

function AudioMiniPlayer({
  audioRef,
  audioUrl,
  playing,
  currentTime,
  duration,
  onPlayPause,
  onSeek,
  onTimeUpdate,
  onLoadedMetadata,
  onEnded,
}: AudioMiniPlayerProps) {
  return (
    <div className="flex items-center gap-3 border-t border-border bg-background px-6 py-3">
      {/* Hidden HTML5 audio element */}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio
        ref={audioRef}
        src={audioUrl}
        onTimeUpdate={onTimeUpdate}
        onLoadedMetadata={onLoadedMetadata}
        onEnded={onEnded}
      />

      {/* Play/Pause */}
      <button
        onClick={onPlayPause}
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground hover:bg-primary/90"
        aria-label={playing ? "Pause" : "Play"}
      >
        {playing ? <Pause size={14} /> : <Play size={14} />}
      </button>

      {/* Current time */}
      <span className="w-10 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
        {formatMmSs(currentTime)}
      </span>

      {/* Scrubber */}
      <input
        type="range"
        min={0}
        max={duration || 0}
        step={0.5}
        value={currentTime}
        onChange={(e) => onSeek(parseFloat(e.target.value))}
        className="flex-1 accent-primary"
        aria-label="Audio seek"
      />

      {/* Duration */}
      <span className="w-10 shrink-0 text-xs tabular-nums text-muted-foreground">
        {formatMmSs(duration)}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Video player (S121)
// ---------------------------------------------------------------------------

interface VideoPlayerProps {
  videoRef: React.RefObject<HTMLVideoElement | null>
  videoUrl: string
}

function VideoPlayer({ videoRef, videoUrl }: VideoPlayerProps) {
  return (
    <div className="mb-4 overflow-hidden rounded-lg border border-border bg-black">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <video ref={videoRef} src={videoUrl} controls className="w-full" />
    </div>
  )
}

// ---------------------------------------------------------------------------
// PredictPanel (S140) — Predict-then-Run for code sections
// ---------------------------------------------------------------------------

interface CodeExecuteResult {
  stdout: string
  stderr: string
  exit_code: number
  elapsed_ms: number
  prediction_correct: boolean | null
  prediction_diff: string | null
}

/** Detect whether a section preview contains a fenced code block.
 * Uses a tight pattern: preview must contain a newline-delimited ``` fence.
 * Avoids false positives from inline backtick sequences.
 */
function hasCodeFence(preview: string): boolean {
  return /^```\w*/m.test(preview) && preview.includes("\n")
}

/** Extract the first fenced code block from a preview string.
 * Falls back to the full preview if no fence is found. Limits to 2000 chars.
 */
function extractCodeFromPreview(preview: string): string {
  const match = /```[\w]*\n([\s\S]*?)(?:```|$)/.exec(preview)
  const code = match ? match[1] : preview
  return code.slice(0, 2000)
}

interface PredictPanelProps {
  sectionId: string
  documentId: string
  preview: string
}

function PredictPanel({ sectionId: _sectionId, documentId, preview }: PredictPanelProps) {
  const [predictOpen, setPredictOpen] = useState(false)
  const [expectedOutput, setExpectedOutput] = useState("")
  const [isRunning, setIsRunning] = useState(false)
  const [runResult, setRunResult] = useState<CodeExecuteResult | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [createCardOpen, setCreateCardOpen] = useState(false)
  const [createSuccess, setCreateSuccess] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const code = extractCodeFromPreview(preview)

  async function handleRunAndCompare() {
    setIsRunning(true)
    setRunError(null)
    setRunResult(null)
    setCreateCardOpen(false)
    setCreateSuccess(false)
    setCreateError(null)

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const resp = await fetch(`${API_BASE}/code/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          code,
          language: "python",
          expected_output: expectedOutput.trim() !== "" ? expectedOutput : undefined,
          document_id: documentId,
        }),
      })
      if (!resp.ok) {
        const body = (await resp.json()) as { detail?: string }
        setRunError(body.detail ?? `Execution failed (HTTP ${resp.status})`)
        return
      }
      const data = (await resp.json()) as CodeExecuteResult
      setRunResult(data)
    } catch (err) {
      if ((err as { name?: string }).name !== "AbortError") {
        setRunError("Execution failed. Check your connection.")
      }
    } finally {
      setIsRunning(false)
      abortRef.current = null
    }
  }

  function handleKill() {
    abortRef.current?.abort()
    setIsRunning(false)
    setRunError("Execution cancelled.")
  }

  async function handleCreateFlashcard() {
    if (!runResult) return
    setCreateError(null)
    const question = `What does this code output?\n\n\`\`\`python\n${code.slice(0, 500)}\n\`\`\``
    const answer = `Correct output:\n${runResult.stdout}${runResult.prediction_diff ? `\n\nDiff:\n${runResult.prediction_diff}` : ""}`
    try {
      const resp = await fetch(`${API_BASE}/flashcards/create-trace`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          answer,
          source_excerpt: code.slice(0, 500),
          document_id: documentId,
        }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      setCreateSuccess(true)
      setCreateCardOpen(false)
    } catch {
      setCreateError("Failed to create flashcard. Please try again.")
    }
  }

  if (!predictOpen) {
    return (
      <button
        onClick={() => setPredictOpen(true)}
        title="Predict the output before running"
        className="mt-1.5 flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs text-muted-foreground hover:border-primary hover:text-primary"
      >
        <Terminal size={10} />
        Predict
      </button>
    )
  }

  return (
    <div className="mt-2 flex flex-col gap-2 rounded-md border border-border bg-muted/30 p-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-foreground">What will this output?</span>
        <button
          onClick={() => { setPredictOpen(false); setRunResult(null); setRunError(null); setCreateCardOpen(false); setCreateSuccess(false) }}
          className="text-muted-foreground hover:text-foreground"
          aria-label="Close predict panel"
        >
          <X size={12} />
        </button>
      </div>

      {/* Expected output input */}
      <textarea
        value={expectedOutput}
        onChange={(e) => setExpectedOutput(e.target.value)}
        placeholder="Type your prediction..."
        rows={2}
        className="w-full resize-none rounded border border-border bg-background px-2 py-1 font-mono text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
      />

      {/* Run / Kill buttons */}
      <div className="flex gap-2">
        <button
          onClick={() => void handleRunAndCompare()}
          disabled={isRunning}
          className="flex items-center gap-1 rounded bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {isRunning && <Loader2 size={10} className="animate-spin" />}
          {isRunning ? "Running..." : "Run and Compare"}
        </button>
        {isRunning && (
          <button
            onClick={handleKill}
            className="rounded border border-destructive px-2.5 py-1 text-xs text-destructive hover:bg-destructive/10"
          >
            Kill
          </button>
        )}
      </div>

      {/* Error state */}
      {runError && (
        <div className="rounded border border-destructive/40 bg-destructive/10 px-2 py-1 text-xs text-destructive">
          {runError}
          <button
            onClick={() => void handleRunAndCompare()}
            className="ml-2 underline hover:no-underline"
          >
            Retry
          </button>
        </div>
      )}

      {/* Result panel */}
      {runResult && (
        <div className="flex flex-col gap-1.5">
          {/* stdout */}
          <div>
            <span className="text-xs text-muted-foreground">Output:</span>
            <pre className="mt-0.5 overflow-auto rounded border border-border bg-background px-2 py-1 font-mono text-xs text-foreground">
              {runResult.stdout || <em className="text-muted-foreground">(no output)</em>}
            </pre>
          </div>

          {/* stderr (only if non-empty) */}
          {runResult.stderr && (
            <div>
              <span className="text-xs text-muted-foreground">stderr:</span>
              <pre className="mt-0.5 overflow-auto rounded border border-destructive/40 bg-destructive/5 px-2 py-1 font-mono text-xs text-destructive">
                {runResult.stderr}
              </pre>
            </div>
          )}

          {/* Prediction result banner */}
          {runResult.prediction_correct !== null && (
            <>
              {runResult.prediction_correct ? (
                <div className="flex items-center gap-1.5 rounded border border-green-400/40 bg-green-50 px-2 py-1 text-xs text-green-700">
                  <Check size={12} />
                  Your prediction was correct!
                </div>
              ) : (
                <div className="flex flex-col gap-1.5">
                  <div className="rounded border border-amber-400/40 bg-amber-50 px-2 py-1 text-xs text-amber-800">
                    Your prediction was wrong.
                    {runResult.prediction_diff && (
                      <pre className="mt-1 overflow-auto font-mono text-xs text-amber-900">
                        {runResult.prediction_diff}
                      </pre>
                    )}
                  </div>

                  {/* Mistake-to-flashcard CTA */}
                  {!createSuccess && (
                    <div className="flex flex-col gap-1">
                      {!createCardOpen ? (
                        <button
                          onClick={() => setCreateCardOpen(true)}
                          className="self-start rounded border border-border px-2.5 py-1 text-xs text-muted-foreground hover:border-primary hover:text-primary"
                        >
                          Create flashcard from this mistake?
                        </button>
                      ) : (
                        <div className="flex flex-col gap-1">
                          {createError && (
                            <p className="text-xs text-destructive">{createError}</p>
                          )}
                          <div className="flex gap-2">
                            <button
                              onClick={() => void handleCreateFlashcard()}
                              className="flex items-center gap-1 rounded bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
                            >
                              <Check size={10} />
                              Create Flashcard
                            </button>
                            <button
                              onClick={() => { setCreateCardOpen(false); setCreateError(null) }}
                              className="rounded border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                  {createSuccess && (
                    <p className="text-xs text-green-700">Flashcard created!</p>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Empty state: loading skeleton when no result yet and not running */}
      {!runResult && !isRunning && !runError && (
        <p className="text-xs text-muted-foreground">
          Type your prediction and click "Run and Compare" to see the result.
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// S151: In-document Cmd+F search
// ---------------------------------------------------------------------------

interface DocumentSectionSearchResult {
  section_id: string
  section_heading: string
  match_count: number
  snippet: string
}

// Allow only bare <mark> and </mark> tags in snippet HTML to prevent XSS from
// user-uploaded content. FTS5 snippet() always produces plain <mark>/<\/mark>
// with no attributes, so the strict match is safe and closes the attribute-injection
// bypass present in a lookahead-only approach (e.g. <mark onmouseover="...">) .
function sanitizeSnippet(html: string): string {
  // Strip every HTML tag that is not an exact bare <mark> or </mark>
  return html.replace(/<(?!\/?mark>)[^>]*>/gi, "")
}

// ---------------------------------------------------------------------------
// S152: ResumeBanner
// ---------------------------------------------------------------------------

interface ReadingPosition {
  document_id: string
  last_section_id: string | null
  last_section_heading: string | null
  last_pdf_page: number | null
  last_epub_chapter_index: number | null
}

interface ResumeBannerProps {
  position: ReadingPosition
  onResume: () => void
  onDismiss: () => void
}

function ResumeBanner({ position, onResume, onDismiss }: ResumeBannerProps) {
  const label = position.last_section_heading ?? "your last position"
  const pageInfo =
    position.last_pdf_page != null
      ? ` (page ${position.last_pdf_page})`
      : position.last_epub_chapter_index != null
        ? ` (chapter ${position.last_epub_chapter_index + 1})`
        : ""

  return (
    <div className="flex items-center gap-2 border-b border-border bg-muted/60 px-4 py-2 text-xs">
      <span className="flex-1 text-muted-foreground">
        Resume at <span className="font-medium text-foreground">{label}</span>{pageInfo}?
      </span>
      <button
        onClick={onResume}
        className="rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
      >
        Resume
      </button>
      <button
        onClick={onDismiss}
        className="text-muted-foreground hover:text-foreground"
        aria-label="Dismiss"
      >
        <X size={12} />
      </button>
    </div>
  )
}

interface InDocSearchBarProps {
  documentId: string
  onResults: (results: DocumentSectionSearchResult[]) => void
  onClose: () => void
  hitIndex: number
  totalHits: number
  onPrev: () => void
  onNext: () => void
}

function InDocSearchBar({
  documentId,
  onResults,
  onClose,
  hitIndex,
  totalHits,
  onPrev,
  onNext,
}: InDocSearchBarProps) {
  const [inputValue, setInputValue] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const debouncedQuery = useDebounce(inputValue, 300)

  // Autofocus on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Fetch results when debounced query changes
  useEffect(() => {
    if (!debouncedQuery.trim()) {
      onResults([])
      setError(null)
      return
    }
    setLoading(true)
    setError(null)
    void (async () => {
      try {
        const res = await fetch(
          `${API_BASE}/documents/${encodeURIComponent(documentId)}/search?q=${encodeURIComponent(debouncedQuery)}`,
        )
        if (!res.ok) {
          setError("Search failed")
          onResults([])
        } else {
          const data = (await res.json()) as DocumentSectionSearchResult[]
          onResults(data)
        }
      } catch {
        setError("Search failed")
        onResults([])
      } finally {
        setLoading(false)
      }
    })()
  }, [debouncedQuery, documentId, onResults])

  return (
    <div className="mb-3 flex flex-col gap-1">
      <div className="flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1">
        {loading ? (
          <Loader2 size={12} className="shrink-0 animate-spin text-muted-foreground" />
        ) : (
          <Search size={12} className="shrink-0 text-muted-foreground" />
        )}
        <input
          ref={inputRef}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          placeholder="Search in document..."
          className="flex-1 bg-transparent text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
        />
        {totalHits > 0 && (
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
            {hitIndex + 1} of {totalHits}
          </span>
        )}
        {totalHits > 0 && (
          <>
            <button
              onClick={onPrev}
              title="Previous match"
              className="shrink-0 text-muted-foreground hover:text-foreground"
              aria-label="Previous match"
            >
              <ChevronUp size={12} />
            </button>
            <button
              onClick={onNext}
              title="Next match"
              className="shrink-0 text-muted-foreground hover:text-foreground"
              aria-label="Next match"
            >
              <ChevronDown size={12} />
            </button>
          </>
        )}
        <button
          onClick={onClose}
          title="Close search"
          className="shrink-0 text-muted-foreground hover:text-foreground"
          aria-label="Close search"
        >
          <X size={12} />
        </button>
      </div>
      {error && (
        <p className="text-xs text-destructive">{error}</p>
      )}
      {!loading && !error && debouncedQuery.trim() && totalHits === 0 && (
        <p className="text-xs text-muted-foreground">No matches in this document</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// DocumentReader
// ---------------------------------------------------------------------------

interface DocumentReaderProps {
  documentId: string
  onBack: () => void
  initialSectionId?: string
  initialChunkId?: string
  initialPage?: number  // S148: PDF page to navigate to on mount (from citation deep-link)
}

export function DocumentReader({ documentId, onBack, initialSectionId, initialChunkId, initialPage }: DocumentReaderProps) {
  const qc = useQueryClient()

  const { data: doc, isLoading } = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => fetchDocument(documentId),
    staleTime: 60_000,
  })

  const sectionListRef = useRef<HTMLDivElement>(null)
  const readerContainerRef = useRef<HTMLDivElement>(null)
  const pdfViewerRef = useRef<PDFViewerHandle>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [sheetText, setSheetText] = useState("")
  const [sheetMode, setSheetMode] = useState<ExplainMode>("plain")
  const [openNoteEditor, setOpenNoteEditor] = useState<string | null>(null) // section id
  const [leftTab, setLeftTab] = useState<"sections" | "pdfview" | "bookview" | "read">("sections")
  const [highlightsVisible, setHighlightsVisible] = useState(true)
  const [highlightsPanelOpen, setHighlightsPanelOpen] = useState(false)
  const [pdfCurrentPage, setPdfCurrentPage] = useState(1)
  const pageTimerRef = useRef<ReturnType<typeof setTimeout>>(null)
  
  const handlePageChange = useCallback((page: number) => {
    if (pageTimerRef.current) clearTimeout(pageTimerRef.current)
    pageTimerRef.current = setTimeout(() => {
      setPdfCurrentPage(page)
    }, 100)
  }, [])
  const highlightsPanelRef = useRef<HTMLDivElement>(null)
  const highlightsToggleRef = useRef<HTMLButtonElement>(null)
  const [readSectionId, setReadSectionId] = useState<string | null>(null)
  // S146: tracks whether the PDF View tab has been visited at least once (lazy-mount)
  const [pdfViewVisited, setPdfViewVisited] = useState(false)
  // S149: tracks whether the Book View tab has been visited at least once (lazy-mount)
  const [bookViewVisited, setBookViewVisited] = useState(false)
  // S143: tracks which section's goals are shown in ChapterGoalsPanel; null = show all
  const [activeSectionGoals, setActiveSectionGoals] = useState<string | null>(null)
  // S144: Feynman mode — section id to open dialog for; null = closed
  const [feynmanSection, setFeynmanSection] = useState<string | null>(null)
  // S197: noteCount for "Compare my notes" button visibility
  const [noteCount, setNoteCount] = useState(0)
  // S151: in-document Cmd+F search state
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchResults, setSearchResults] = useState<DocumentSectionSearchResult[]>([])
  const [searchHitIndex, setSearchHitIndex] = useState(0)

  // S152: reading position — resume banner
  const [resumePosition, setResumePosition] = useState<ReadingPosition | null>(null)
  // ref tracking the last section_id we POSTed so we only POST when it changes
  const lastPostedSectionRef = useRef<string | null>(null)
  // throttle timer: one POST per 10 seconds max
  const positionThrottleRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // S147: SelectionActionBar dialog state
  const [selectionNoteOpen, setSelectionNoteOpen] = useState(false)
  const [selectionNoteText, setSelectionNoteText] = useState("")
  const [selectionNoteSourceRef, setSelectionNoteSourceRef] = useState<SourceRef | null>(null)
  const [selectionNoteHeading, setSelectionNoteHeading] = useState<string | undefined>(undefined)
  const [editingCreatedNote, setEditingCreatedNote] = useState<Note | null>(null)
  const [selectionFlashcardOpen, setSelectionFlashcardOpen] = useState(false)
  const [selectionFlashcardText, setSelectionFlashcardText] = useState("")
  const [selectionFlashcardSourceRef, setSelectionFlashcardSourceRef] = useState<SourceRef | null>(null)
  const [selectionFlashcardHeading, setSelectionFlashcardHeading] = useState<string | undefined>(undefined)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const setStudySectionFilter = useAppStore((s) => s.setStudySectionFilter)
  const setChatPreload = useAppStore((s) => s.setChatPreload)

  // Audio mini-player state (S120) — only active for audio documents
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [audioPlaying, setAudioPlaying] = useState(false)
  const [audioCurrentTime, setAudioCurrentTime] = useState(0)
  const [audioDuration, setAudioDuration] = useState(0)

  // Video player state (S121) — only active for video documents
  const videoRef = useRef<HTMLVideoElement | null>(null)

  const isAudio = doc?.content_type === "audio"
  const isVideo = doc?.content_type === "video"
  const isYouTube = isYouTubeDoc(doc ?? {})

  // S111: Pre-calculate section map for O(1) lookups in highlight loops
  const sectionMap = useMemo(() => {
    const m = new Map<string, SectionItem>()
    if (doc?.sections) {
      for (const s of doc.sections) m.set(s.id, s)
    }
    return m
  }, [doc?.sections])

  const audioUrl = (isAudio && !isYouTube) ? `${API_BASE}/documents/${documentId}/audio` : null
  const videoUrl = isVideo ? `${API_BASE}/documents/${documentId}/video` : null

  function handleAudioPlayPause() {
    const el = audioRef.current
    if (!el) return
    if (audioPlaying) {
      el.pause()
      setAudioPlaying(false)
    } else {
      void el.play()
      setAudioPlaying(true)
    }
  }

  function handleAudioSeek(t: number) {
    const el = audioRef.current
    if (!el) return
    el.currentTime = t
    setAudioCurrentTime(t)
  }

  function seekAndPlay(t: number) {
    const el = audioRef.current
    if (!el) return
    el.currentTime = t
    void el.play()
    setAudioPlaying(true)
  }

  function seekAndPlayVideo(t: number) {
    const el = videoRef.current
    if (!el) return
    el.currentTime = t
    void el.play()
  }

  // Scroll to initialSectionId once document sections are loaded (S114)
  useEffect(() => {
    if (!initialSectionId || !doc) return
    // Wait a tick for DOM to update after doc is available
    const timer = setTimeout(() => {
      const el = document.querySelector(`[data-section-id="${initialSectionId}"]`)
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" })
      }
    }, 100)
    return () => clearTimeout(timer)
  }, [initialSectionId, doc])

  // S151: Explicit scroll when switching to Read tab via citation link
  useEffect(() => {
    if (leftTab === "read" && readSectionId) {
      const timer = setTimeout(() => {
        const el = document.getElementById(`read-sec-${readSectionId}`)
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "start" })
        }
      }, 150)
      return () => clearTimeout(timer)
    }
  }, [leftTab, readSectionId])

  // Auto-switch to PDF view for PDF documents; Book view for EPUB; Read view for deep links
  useEffect(() => {
    if (!doc) return
    if (doc.format === "pdf") {
      setPdfViewVisited(true)
      setLeftTab("pdfview")
      if (initialSectionId) setReadSectionId(initialSectionId)
    } else if (initialSectionId || initialChunkId || initialPage) {
      if (initialSectionId) setReadSectionId(initialSectionId)
      setLeftTab("read")
    } else if (doc.format === "epub") {
      setBookViewVisited(true)
      setLeftTab("bookview")
    }
  }, [doc?.format, initialSectionId, initialPage]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch notes for this document so dot indicators persist across reloads (S106)
  const { data: docNotes, isError: notesError } = useQuery<NoteEntry[]>({
    queryKey: ["notes-for-doc", documentId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/notes?document_id=${encodeURIComponent(documentId)}`)
      if (!res.ok) throw new Error("Failed to fetch notes")
      return res.json() as Promise<NoteEntry[]>
    },
    staleTime: 30_000,
  })

  // Fetch annotations for highlight reconstruction and panel (S111)
  const {
    data: docAnnotations,
  } = useQuery<AnnotationItem[]>({
    queryKey: ["annotations-for-doc", documentId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/annotations?document_id=${encodeURIComponent(documentId)}`)
      if (!res.ok) throw new Error("Failed to fetch annotations")
      return res.json() as Promise<AnnotationItem[]>
    },
    staleTime: 30_000,
  })

  // Fetch objective progress for mini rings on section headers (S143)
  const { data: progressData } = useQuery<{
    by_chapter: { section_id: string; progress_pct: number }[]
  }>({
    queryKey: ["doc-progress", documentId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/documents/${documentId}/progress`)
      if (!res.ok) return { by_chapter: [] }
      return res.json() as Promise<{ by_chapter: { section_id: string; progress_pct: number }[] }>
    },
    staleTime: 60_000,
  })

  const progressBySectionId = useMemo(
    () => new Map((progressData?.by_chapter ?? []).map((c) => [c.section_id, c.progress_pct])),
    [progressData],
  )

  // S151: derived set of section IDs that have a search hit (O(1) lookup)
  const searchHitSectionIds = useMemo(
    () => new Set(searchResults.map((r) => r.section_id)),
    [searchResults],
  )

  // S131: Group annotations by section for O(1) retrieval in section list
  const annotationsBySection = useMemo(() => {
    const m = new Map<string, AnnotationItem[]>()
    if (docAnnotations) {
      for (const ann of docAnnotations) {
        const list = m.get(ann.section_id) || []
        list.push(ann)
        m.set(ann.section_id, list)
      }
    }
    return m
  }, [docAnnotations])

  // S151: Pre-calculate search snippet map for O(1) retrieval
  const searchSnippetMap = useMemo(() => {
    const m = new Map<string, string>()
    for (const r of searchResults) {
      if (r.snippet) m.set(r.section_id, r.snippet)
    }
    return m
  }, [searchResults])

  // S151: Cmd+F / Ctrl+F keydown listener — opens inline search bar
  useEffect(() => {
    function handleCmdF(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    document.addEventListener("keydown", handleCmdF)
    return () => document.removeEventListener("keydown", handleCmdF)
  }, [])

  // S151: Escape closes the search bar when it is open
  useEffect(() => {
    if (!searchOpen) return
    function handleEsc(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setSearchOpen(false)
        setSearchResults([])
        setSearchHitIndex(0)
      }
    }
    document.addEventListener("keydown", handleEsc)
    return () => document.removeEventListener("keydown", handleEsc)
  }, [searchOpen])

  // S151: close search bar when switching away from the sections tab
  useEffect(() => {
    if (leftTab !== "sections" && searchOpen) {
      setSearchOpen(false)
      setSearchResults([])
      setSearchHitIndex(0)
    }
  }, [leftTab, searchOpen])

  // S151: scroll current hit into view when hitIndex or results change
  useEffect(() => {
    if (searchResults.length === 0) return
    const targetId = searchResults[searchHitIndex]?.section_id
    if (!targetId) return
    const el = document.querySelector(`[data-section-id="${CSS.escape(targetId)}"]`)
    if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" })
  }, [searchHitIndex, searchResults])

  function handleStudyClick(sid: string) {
    setActiveDocument(documentId)
    setStudySectionFilter({ sectionId: sid, bloomLevelMin: 2 })
  }

  // Fetch FSRS fragility heatmap for section coloring (S116)
  const { data: heatmapData } = useQuery<Record<string, SectionHeatmapItem>>({
    queryKey: ["section-heatmap", documentId],
    queryFn: async () => {
      const res = await fetch(
        `${API_BASE}/study/section-heatmap?document_id=${encodeURIComponent(documentId)}`
      )
      if (!res.ok) return {}
      const data = (await res.json()) as { heatmap: Record<string, SectionHeatmapItem> }
      return data.heatmap
    },
    staleTime: 60_000,
  })

  // Derive the set of section IDs that have at least one note
  const notedSections = useMemo(
    () => new Set((docNotes ?? []).map((n) => n.section_id).filter((id): id is string => id !== null && id !== undefined)),
    [docNotes],
  )

  // Track reading progress via IntersectionObserver (3-second dwell per section)
  useReadingProgress(documentId, doc?.sections.length ?? 0)

  // S152: fetch saved reading position on mount; show ResumeBanner unless already dismissed this session
  useEffect(() => {
    if (!doc) return
    const dismissedKey = `resume-dismissed-${documentId}`
    if (sessionStorage.getItem(dismissedKey)) return
    void fetch(`${API_BASE}/documents/${documentId}/position`)
      .then((r) => {
        if (r.status === 404) return null
        if (!r.ok) return null
        return r.json() as Promise<ReadingPosition>
      })
      .then((pos) => {
        if (pos?.last_section_id) setResumePosition(pos)
      })
      .catch(() => {
        // banner failure is silent — reader remains fully functional
      })
  }, [documentId, doc])

  // S152: IntersectionObserver — track the topmost visible section and throttle-POST position
  useEffect(() => {
    if (!doc || doc.sections.length === 0) return
    const sectionElements = Array.from(
      document.querySelectorAll<HTMLElement>("[data-section-id]"),
    )
    if (sectionElements.length === 0) return

    function postPosition(sectionId: string) {
      if (sectionId === lastPostedSectionRef.current) return
      // throttle: clear any pending timer and set a new one (fire after 10s of no-change)
      if (positionThrottleRef.current) clearTimeout(positionThrottleRef.current)
      positionThrottleRef.current = setTimeout(() => {
        const section = doc!.sections.find((s) => s.id === sectionId)
        void fetch(`${API_BASE}/documents/${documentId}/position`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            last_section_id: sectionId,
            last_section_heading: section?.heading ?? null,
            last_pdf_page: null,
            last_epub_chapter_index: null,
          }),
        }).catch(() => {
          // best-effort; ignore network errors silently
        })
        lastPostedSectionRef.current = sectionId
      }, 10_000)
    }

    const observer = new IntersectionObserver(
      (entries) => {
        // find the topmost intersecting section
        let topmost: HTMLElement | null = null
        let topmostTop = Infinity
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const top = entry.boundingClientRect.top
            if (top < topmostTop) {
              topmostTop = top
              topmost = entry.target as HTMLElement
            }
          }
        }
        if (topmost?.dataset.sectionId) {
          postPosition(topmost.dataset.sectionId)
        }
      },
      { threshold: 0.2 },
    )

    for (const el of sectionElements) observer.observe(el)
    return () => {
      observer.disconnect()
      if (positionThrottleRef.current) clearTimeout(positionThrottleRef.current)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId, doc?.sections.length])

  // S152: resume — scroll to last_section_id and dismiss banner
  function handleResume() {
    if (!resumePosition?.last_section_id) return
    const el = document.querySelector(`[data-section-id="${CSS.escape(resumePosition.last_section_id)}"]`)
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" })
    setResumePosition(null)
    sessionStorage.setItem(`resume-dismissed-${documentId}`, "1")
  }

  // S152: start over — dismiss banner without scrolling, store in sessionStorage
  function handleDismissResume() {
    setResumePosition(null)
    sessionStorage.setItem(`resume-dismissed-${documentId}`, "1")
  }

  // S146: mark PDF view visited for lazy mounting; guard against pdfview on non-PDF docs
  // S149: mark Book View visited for lazy mounting; guard against bookview on non-EPUB docs
  useEffect(() => {
    if (leftTab === "pdfview") {
      if (doc?.format !== "pdf") {
        setLeftTab("sections")
      } else {
        setPdfViewVisited(true)
      }
    } else if (leftTab === "bookview") {
      if (doc?.format !== "epub") {
        setLeftTab("sections")
      } else {
        setBookViewVisited(true)
      }
    }
  }, [leftTab, doc?.format])

  // Close highlights panel on outside click
  useEffect(() => {
    if (!highlightsPanelOpen) return
    function handleClick(e: MouseEvent) {
      if (
        highlightsPanelRef.current?.contains(e.target as Node) ||
        highlightsToggleRef.current?.contains(e.target as Node)
      ) return
      setHighlightsPanelOpen(false)
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [highlightsPanelOpen])

  // Navigate to a highlight: for PDF annotations go to PDF page, otherwise Read tab
  function navigateToHighlight(ann: AnnotationItem) {
    setHighlightsPanelOpen(false)

    const isAlreadyPdf = leftTab === "pdfview" && pdfViewVisited

    // PDF highlight with page number -- jump to that page in PDF view
    if (ann.page_number != null && doc?.format === "pdf") {
      setPdfViewVisited(true)
      setLeftTab("pdfview")
      if (isAlreadyPdf) {
        pdfViewerRef.current?.goToPage(ann.page_number)
      } else {
        // Small delay to ensure PDF viewer tab is mounted before calling goToPage
        setTimeout(() => pdfViewerRef.current?.goToPage(ann.page_number!), 50)
      }
      return
    }
    // PDF highlight without page_number but with section -- use section page_start
    if (doc?.format === "pdf") {
      const sec = sectionMap.get(ann.section_id)
      if (sec && sec.page_start > 0) {
        setPdfViewVisited(true)
        setLeftTab("pdfview")
        if (isAlreadyPdf) {
          pdfViewerRef.current?.goToPage(sec.page_start)
        } else {
          setTimeout(() => pdfViewerRef.current?.goToPage(sec.page_start), 50)
        }
        return
      }
    }
    // Non-PDF: go to Read view and scroll to section
    if (leftTab !== "read") {
      setReadSectionId(ann.section_id)
      setLeftTab("read")
    } else {
      const el = document.getElementById(`read-sec-${ann.section_id}`)
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }

  async function handleDeleteHighlight(id: string) {
    try {
      await fetch(`${API_BASE}/annotations/${id}`, { method: "DELETE" })
      void qc.invalidateQueries({ queryKey: ["annotations-for-doc", documentId] })
      toast.success("Highlight removed")
    } catch {
      toast.error("Failed to delete highlight")
    }
  }

  function handleExplain(text: string, mode: ExplainMode) {
    setSheetText(text)
    setSheetMode(mode)
    setSheetOpen(true)
  }

  // S147/S198: walk up DOM from startContainer looking for [data-section-id] attribute
  function resolveSourceRef(startContainer: Node): SourceRef {
    // DOM walk: works for section list view, ReadView, and any view with data-section-id
    const sectionId = resolveFromDom(startContainer)
    if (sectionId) {
      return { sectionId, documentId, documentTitle: doc?.title ?? "" }
    }

    // Fallback for PDF view: map currentPage to section by page range
    if (leftTab === "pdfview" && doc?.sections && doc.sections.length > 0) {
      const pdfSectionId = resolvePdfFallback(doc.sections, pdfCurrentPage, doc.page_count)
      if (pdfSectionId) {
        return { sectionId: pdfSectionId, documentId, documentTitle: doc?.title ?? "" }
      }
    }

    // Fallback for read view: use first section when DOM walk failed
    if (leftTab === "read" && doc?.sections && doc.sections.length > 0) {
      return { sectionId: doc.sections[0].id, documentId, documentTitle: doc?.title ?? "" }
    }

    return { sectionId: undefined, documentId, documentTitle: doc?.title ?? "" }
  }

  function handleSelectionAddToNote(text: string, sourceRef: SourceRef) {
    const heading = sourceRef.sectionId
      ? doc?.sections.find((s) => s.id === sourceRef.sectionId)?.heading
      : undefined
    setSelectionNoteText(text)
    setSelectionNoteSourceRef(sourceRef)
    setSelectionNoteHeading(heading)
    setSelectionNoteOpen(true)
  }

  function handleSelectionCreateFlashcard(text: string, sourceRef: SourceRef) {
    const heading = sourceRef.sectionId
      ? doc?.sections.find((s) => s.id === sourceRef.sectionId)?.heading
      : undefined
    setSelectionFlashcardText(text)
    setSelectionFlashcardSourceRef(sourceRef)
    setSelectionFlashcardHeading(heading)
    setSelectionFlashcardOpen(true)
  }

  function handleSelectionAskInChat(text: string, sourceRef: SourceRef) {
    setChatPreload({ text: `Regarding this passage:\n> "${text}"\n\nMy question: `, documentId: sourceRef.documentId })
    useAppStore.getState().setChatPanelOpen(true)
  }

  async function handleSelectionHighlight(text: string, sourceRef: SourceRef, color: string = "yellow") {
    if (!sourceRef.sectionId) return
    const pageNumber = leftTab === "pdfview" ? pdfCurrentPage : null
    try {
      await fetch(`${API_BASE}/annotations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: documentId,
          section_id: sourceRef.sectionId,
          chunk_id: null,
          selected_text: text,
          start_offset: 0,
          end_offset: text.length,
          color,
          note_text: null,
          page_number: pageNumber,
        }),
      })
      void qc.invalidateQueries({ queryKey: ["annotations-for-doc", documentId] })
      toast.success("Highlighted")
    } catch {
      toast.error("Failed to save highlight")
    }
  }

  async function handleSelectionClip(text: string, sourceRef: SourceRef) {
    const heading = sourceRef.sectionId
      ? doc?.sections.find((s) => s.id === sourceRef.sectionId)?.heading
      : undefined
    try {
      await fetch(`${API_BASE}/clips`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: sourceRef.documentId,
          section_id: sourceRef.sectionId ?? null,
          section_heading: heading ?? null,
          pdf_page_number: null,
          selected_text: text,
          user_note: "",
        }),
      })
      toast.success("Passage clipped")
    } catch {
      toast.error("Failed to save clip. Please try again.")
    }
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

  // Pre-render highlights list items (avoids useMemo inside JSX which is illegal)
  const renderedHighlightItems = (docAnnotations ?? []).map((ann) => {
    const sectionHeading = sectionMap.get(ann.section_id)?.heading ?? ""
    return (
      <li key={ann.id} className="flex items-start gap-2 px-3 py-2 hover:bg-accent/50 group">
        <span className={cn("mt-1 h-2.5 w-2.5 shrink-0 rounded-full", COLOR_CLASSES[ann.color] ?? COLOR_CLASSES.yellow)} />
        <button
          onClick={() => navigateToHighlight(ann)}
          className="min-w-0 flex-1 text-left"
        >
          <p className="truncate text-xs text-foreground" title={ann.selected_text}>
            {ann.selected_text.length > 50 ? `${ann.selected_text.slice(0, 50)}...` : ann.selected_text}
          </p>
          {sectionHeading && (
            <p className="truncate text-[10px] text-muted-foreground">{sectionHeading}</p>
          )}
        </button>
        <button
          onClick={() => void handleDeleteHighlight(ann.id)}
          title="Remove highlight"
          className="shrink-0 mt-0.5 text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive transition-opacity"
        >
          <Trash2 size={12} />
        </button>
      </li>
    )
  })

  // Pre-compute section list items (performance comes from the O(1) Map lookups above)
  const renderedSectionItems = doc.sections.map((section) => {
    const hasNote = notedSections.has(section.id)
    const editorOpen = openNoteEditor === section.id
    const heatmapItem = heatmapData?.[section.id] ?? null
    const fragilityClass = fragilityBorderClass(heatmapItem?.fragility_score ?? null)
    const sectionBorderClass = section.admonition_type
      ? admonitionClass(section.admonition_type)
      : fragilityClass
    const tooltipText =
      heatmapItem && heatmapItem.fragility_score !== null
        ? `${heatmapItem.due_card_count} card${heatmapItem.due_card_count !== 1 ? "s" : ""} due, avg retention ${heatmapItem.avg_retention_pct ?? 0}%`
        : undefined
    const mediaStartTime = (isAudio || isVideo || isYouTube) ? parseAudioStartTime(section.heading) : null
    return (
      <li
        key={section.id}
        data-section-id={section.id}
        title={tooltipText}
        className={cn(
          "rounded-md border border-border p-3",
          sectionBorderClass,
          searchHitSectionIds.has(section.id) && "ring-2 ring-primary",
        )}
      >
        <div className="flex items-start gap-1">
          <p
            className="flex-1 text-sm font-semibold text-foreground"
            style={{ paddingLeft: `${(section.level - 1) * 12}px` }}
          >
            {section.admonition_type && (
              <span
                className="mr-1 rounded px-1 py-0.5 text-xs font-bold uppercase tracking-wide"
                style={{ color: ADMONITION_LABEL_COLORS[section.admonition_type] ?? "inherit" }}
              >
                {section.admonition_type}
              </span>
            )}
            {section.heading || "(Untitled section)"}
          </p>
          <button
            onClick={() => {
              setReadSectionId(section.id)
              setLeftTab("read")
            }}
            title="Read from this section"
            className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground"
          >
            <BookOpen size={12} />
          </button>
          {doc.format === "pdf" && section.page_start > 0 && (
            <button
              onClick={() => {
                setPdfViewVisited(true)
                setLeftTab("pdfview")
                pdfViewerRef.current?.goToPage(section.page_start)
              }}
              title={`Open PDF at page ${section.page_start}`}
              className="mt-0.5 shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs tabular-nums text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              p.{section.page_start}
            </button>
          )}
          {mediaStartTime !== null && (
            isYouTube && doc?.source_url ? (
              <a
                href={buildYouTubeTimestampUrl(doc.source_url, mediaStartTime)}
                target="_blank"
                rel="noopener noreferrer"
                title={`Open YouTube at ${formatMmSs(mediaStartTime)}`}
                className="mt-0.5 shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs tabular-nums text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                {formatMmSs(mediaStartTime)}
              </a>
            ) : (
              <button
                onClick={() => isAudio ? seekAndPlay(mediaStartTime) : seekAndPlayVideo(mediaStartTime)}
                title={`Play from ${formatMmSs(mediaStartTime)}`}
                className="mt-0.5 shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs tabular-nums text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                {formatMmSs(mediaStartTime)}
              </button>
            )
          )}
          {progressBySectionId.has(section.id) && (
            <button
              onClick={() => setActiveSectionGoals(
                activeSectionGoals === section.id ? null : section.id
              )}
              title={`${Math.round(progressBySectionId.get(section.id) ?? 0)}% objectives covered`}
              className="mt-0.5 shrink-0"
            >
              <ChapterProgressRing pct={progressBySectionId.get(section.id) ?? 0} size={12} />
            </button>
          )}
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
          {(doc.content_type === "tech_book" || doc.content_type === "tech_article") && (
            <button
              onClick={() => setFeynmanSection(section.id)}
              title="Practice Feynman technique for this section"
              className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground"
            >
              <Brain size={12} />
            </button>
          )}
        </div>
        {section.preview && (
          <SectionPreviewWithHighlights
            preview={section.preview}
            annotations={annotationsBySection.get(section.id) ?? []}
            sectionId={section.id}
            searchSnippet={searchSnippetMap.get(section.id)}
          />
        )}
        {section.preview && hasCodeFence(section.preview) && (
          <PredictPanel
            sectionId={section.id}
            documentId={documentId}
            preview={section.preview}
          />
        )}
        {editorOpen && (
          <NoteEditor
            documentId={documentId}
            sectionId={section.id}
            onSaved={() => {
              setOpenNoteEditor(null)
              void qc.invalidateQueries({ queryKey: ["notes-for-doc", documentId] })
              void qc.invalidateQueries({ queryKey: ["reader-notes"] })
              void qc.invalidateQueries({ queryKey: ["notes"] })
              void qc.invalidateQueries({ queryKey: ["notes-groups"] })
              void qc.invalidateQueries({ queryKey: ["collections"] })
            }}
            onCancel={() => setOpenNoteEditor(null)}
          />
        )}
      </li>
    )
  })

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Back button + Compare my notes (S197) */}
      <div className="flex items-center justify-between border-b border-border px-6 py-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft size={14} />
          Back to library
        </button>
        {noteCount >= 3 && (
          <button
            onClick={() => {
              setChatPreload({ text: "compare my notes with this book", documentId, autoSubmit: true })
              window.dispatchEvent(
                new CustomEvent("luminary:navigate", { detail: { tab: "chat" } })
              )
            }}
            className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted transition-colors"
          >
            <GitCompareArrows size={14} />
            Compare my notes
          </button>
        )}
      </div>

      {/* Two-panel layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left panel — 60%; relative for SelectionActionBar absolute positioning */}
        <div ref={readerContainerRef} className="relative flex w-3/5 flex-col overflow-hidden border-r border-border">
          {/* Document header — hidden in PDF/Book view to maximise canvas area */}
          {leftTab !== "pdfview" && leftTab !== "bookview" && leftTab !== "read" && (
            <>
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

              {/* S152: Resume banner — shown once per session when a saved position exists */}
              {resumePosition && (
                <ResumeBanner
                  position={resumePosition}
                  onResume={handleResume}
                  onDismiss={handleDismissResume}
                />
              )}
            </>
          )}

          {/* Left panel tab bar — Sections / Read / PDF View (PDF only) / Book View (EPUB only) + highlight toggle */}
          <div className="flex border-b border-border">
            {(doc.format === "pdf"
              ? (["sections", "read", "pdfview"] as const)
              : doc.format === "epub"
                ? (["sections", "read", "bookview"] as const)
                : (["sections", "read"] as const)
            ).map((tab) => (
              <button
                key={tab}
                onClick={() => setLeftTab(tab)}
                className={cn(
                  "flex-1 py-2 text-xs font-medium transition-colors",
                  leftTab === tab
                    ? "border-b-2 border-primary text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {tab === "pdfview"
                  ? "PDF View"
                  : tab === "bookview"
                    ? "Book View"
                    : tab === "read"
                      ? "Read"
                      : "Sections"}
              </button>
            ))}
            {/* Highlight visibility toggle + dropdown */}
            <div className="relative flex items-center">
              <button
                onClick={() => setHighlightsVisible((v) => !v)}
                title={highlightsVisible ? "Hide highlights" : "Show highlights"}
                className={cn(
                  "relative flex items-center justify-center px-2 py-2 text-xs transition-colors",
                  highlightsVisible
                    ? "text-yellow-600 dark:text-yellow-400"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Highlighter size={14} />
                {(docAnnotations ?? []).length > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 flex h-3.5 min-w-[14px] items-center justify-center rounded-full bg-primary px-0.5 text-[9px] font-bold text-primary-foreground">
                    {(docAnnotations ?? []).length}
                  </span>
                )}
              </button>
              {(docAnnotations ?? []).length > 0 && (
                <button
                  ref={highlightsToggleRef}
                  onClick={() => setHighlightsPanelOpen((v) => !v)}
                  title="Manage highlights"
                  className="flex items-center justify-center px-1 py-2 text-muted-foreground hover:text-foreground"
                >
                  <ChevronRight size={10} className={cn("transition-transform", highlightsPanelOpen && "rotate-90")} />
                </button>
              )}
              {/* Highlights dropdown panel */}
              {highlightsPanelOpen && (docAnnotations ?? []).length > 0 && (
                <div
                  ref={highlightsPanelRef}
                  className="absolute top-full right-0 z-50 mt-1 w-72 max-h-64 overflow-auto rounded-lg border border-border bg-background shadow-xl"
                >
                  <div className="px-3 py-2 border-b border-border">
                    <p className="text-xs font-medium text-foreground">{(docAnnotations ?? []).length} highlight{(docAnnotations ?? []).length !== 1 ? "s" : ""}</p>
                  </div>
                  <ul className="divide-y divide-border">
                    {renderedHighlightItems}
                  </ul>
                </div>
              )}
            </div>
          </div>

          {/* S146: PDF View — lazy-mounted, hidden when not active to preserve page state */}
          {doc.format === "pdf" && pdfViewVisited && (() => {
            let targetPdfPage = initialPage
            if (!targetPdfPage && initialSectionId) {
              const sec = doc.sections.find((s) => s.id === initialSectionId)
              if (sec && sec.page_start > 0) targetPdfPage = sec.page_start
            }
            return (
              <div className={cn("flex-1 overflow-hidden", leftTab !== "pdfview" && "hidden")}>
                <PDFViewer ref={pdfViewerRef} documentId={documentId} sections={doc.sections} initialPage={targetPdfPage} annotations={docAnnotations ?? []} highlightsVisible={highlightsVisible} onPageChange={handlePageChange} />
              </div>
            )
          })()}

          {/* S149: Book View — lazy-mounted for EPUB documents */}
          {bookViewVisited && (
            <div className={cn("flex-1 overflow-hidden", leftTab !== "bookview" && "hidden")}>
              <EPUBViewer documentId={documentId} />
            </div>
          )}

          {/* Read View — full document content as markdown, or transcript for YouTube */}
          <div className={cn("flex-1 overflow-hidden", leftTab !== "read" && "hidden")}>
            {isYouTube ? (
              <YouTubeTranscriptView doc={doc} initialSectionId={readSectionId} initialChunkId={initialChunkId} />
            ) : (
              <ReadView
                documentId={documentId}
                initialSectionId={readSectionId}
                annotations={docAnnotations ?? []}
                highlightsVisible={highlightsVisible}
              />
            )}
          </div>

          {/* S147: SelectionActionBar — fires on selections in both section list and PDF viewer */}
          <SelectionActionBar
            containerRef={readerContainerRef}
            resolveSourceRef={resolveSourceRef}
            onExplain={handleExplain}
            onAddToNote={handleSelectionAddToNote}
            onCreateFlashcard={handleSelectionCreateFlashcard}
            onAskInChat={handleSelectionAskInChat}
            onHighlight={(text, sourceRef, color) => void handleSelectionHighlight(text, sourceRef, color)}
            onClip={(text, sourceRef) => void handleSelectionClip(text, sourceRef)}
          />

          {/* Section list */}
          <div
            ref={sectionListRef}
            className={cn(
              "relative flex-1 overflow-auto pb-6",
              (leftTab === "pdfview" || leftTab === "bookview" || leftTab === "read") && "hidden",
            )}
          >
            {leftTab === "sections" && (
              <>
                {notesError && (
                  <p className="mb-2 px-6 pt-3 text-xs text-muted-foreground">
                    Note indicators unavailable — could not load notes.
                  </p>
                )}
                <div className="px-6 pt-3">
                  {/* S151: Inline search bar — shown when Cmd+F is pressed */}
                  {searchOpen && (
                    <InDocSearchBar
                      documentId={documentId}
                      onResults={(results) => {
                        setSearchResults(results)
                        setSearchHitIndex(0)
                      }}
                      onClose={() => {
                        setSearchOpen(false)
                        setSearchResults([])
                        setSearchHitIndex(0)
                      }}
                      hitIndex={searchHitIndex}
                      totalHits={searchResults.length}
                      onPrev={() =>
                        setSearchHitIndex((i) =>
                          (i - 1 + searchResults.length) % searchResults.length,
                        )
                      }
                      onNext={() =>
                        setSearchHitIndex((i) => (i + 1) % searchResults.length)
                      }
                    />
                  )}
                  {doc.sections.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No sections detected.</p>
                  ) : (
                    <ul className="space-y-3">
                      {renderedSectionItems}
                    </ul>
                  )}
                </div>
              </>
            )}
          </div>
        </div>

        {/* Right panel — 40%, sticky */}
        <div className="w-2/5 overflow-auto p-6">
          {/* Video player for video documents (S121) */}
          {isVideo && videoUrl && (
            <VideoPlayer videoRef={videoRef} videoUrl={videoUrl} />
          )}
          {/* Chapter Goals panel — only visible for tech_book/tech_article with extracted objectives */}
          <ChapterGoalsPanel
            documentId={documentId}
            sectionId={activeSectionGoals}
            onStudyClick={handleStudyClick}
          />
          <SummaryPanel
            documentId={documentId}
            contentType={doc.content_type}
            activeSectionId={readSectionId}
            onNoteCountKnown={setNoteCount}
            onScrollToSection={(sectionId) => {
              if (leftTab !== "read") {
                setReadSectionId(sectionId)
                setLeftTab("read")
              } else {
                const el = document.getElementById(`read-sec-${sectionId}`)
                if (el) el.scrollIntoView({ behavior: "smooth", block: "start" })
              }
            }}
          />
        </div>
      </div>

      {/* Audio mini-player — sticky bottom bar, audio documents only (S120) */}
      {isAudio && audioUrl && (
        <AudioMiniPlayer
          audioRef={audioRef}
          audioUrl={audioUrl}
          playing={audioPlaying}
          currentTime={audioCurrentTime}
          duration={audioDuration}
          onPlayPause={handleAudioPlayPause}
          onSeek={handleAudioSeek}
          onTimeUpdate={() => {
            if (audioRef.current) setAudioCurrentTime(audioRef.current.currentTime)
          }}
          onLoadedMetadata={() => {
            if (audioRef.current) setAudioDuration(audioRef.current.duration)
          }}
          onEnded={() => setAudioPlaying(false)}
        />
      )}

      {/* Feynman dialog (S144) */}
      {feynmanSection && (
        <FeynmanDialog
          documentId={documentId}
          sectionId={feynmanSection}
          concept={doc.sections.find((s) => s.id === feynmanSection)?.heading ?? ""}
          onClose={() => setFeynmanSection(null)}
        />
      )}

      {/* S147: Note creation dialog — pre-filled with selected text blockquote */}
      <NoteCreationDialog
        open={selectionNoteOpen}
        selectedText={selectionNoteText}
        sourceRef={selectionNoteSourceRef}
        sectionHeading={selectionNoteHeading}
        onClose={() => setSelectionNoteOpen(false)}
        onSaved={(note: Note) => {
          void qc.invalidateQueries({ queryKey: ["notes-for-doc", documentId] })
          void qc.invalidateQueries({ queryKey: ["reader-notes"] })
          void qc.invalidateQueries({ queryKey: ["notes"] })
          void qc.invalidateQueries({ queryKey: ["notes-groups"] })
          void qc.invalidateQueries({ queryKey: ["collections"] })
          setEditingCreatedNote(note)
        }}
      />

      {/* NoteEditorDialog -- opens after NoteCreationDialog saves for full editing */}
      <NoteEditorDialog
        note={editingCreatedNote}
        onClose={() => setEditingCreatedNote(null)}
        onSaved={(_updated) => {
          void qc.invalidateQueries({ queryKey: ["notes-for-doc", documentId] })
          void qc.invalidateQueries({ queryKey: ["reader-notes"] })
          void qc.invalidateQueries({ queryKey: ["notes"] })
          void qc.invalidateQueries({ queryKey: ["notes-groups"] })
          void qc.invalidateQueries({ queryKey: ["collections"] })
          setEditingCreatedNote(null)
        }}
      />

      {/* S147: Flashcard generation dialog — scoped to selected text context */}
      <DocumentFlashcardDialog
        open={selectionFlashcardOpen}
        documentId={documentId}
        sectionId={selectionFlashcardSourceRef?.sectionId}
        sectionHeading={selectionFlashcardHeading}
        context={selectionFlashcardText}
        onClose={() => setSelectionFlashcardOpen(false)}
      />

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
