import { BookOpen, Brain, Check, ChevronDown, ChevronRight, StickyNote, X } from "lucide-react"
import { memo, useState } from "react"

import { API_BASE } from "@/lib/config"
import { cn } from "@/lib/utils"

import { ChapterProgressRing } from "./ChapterGoalsPanel"
import { SectionPreviewWithHighlights } from "./HighlightsPanel"
import { formatMmSs, parseAudioStartTime } from "./mediaUtils"
import { PredictPanel, hasCodeFence } from "./PredictPanel"
import type { AnnotationItem, SectionItem } from "./types"

export interface SectionHeatmapItem {
  section_id: string
  fragility_score: number | null
  due_card_count: number
  avg_retention_pct: number | null
}

export function fragilityBorderClass(score: number | null): string {
  if (score === null) return ""
  if (score <= 0.3) return "border-l-4 border-l-green-500"
  if (score <= 0.6) return "border-l-4 border-l-yellow-500"
  return "border-l-4 border-l-red-500"
}

function RetentionChip({ heatmap }: { heatmap: SectionHeatmapItem | null }) {
  if (!heatmap || heatmap.fragility_score === null) return null
  const retentionPct = heatmap.avg_retention_pct ?? Math.round((1 - heatmap.fragility_score) * 100)
  const tone =
    heatmap.fragility_score <= 0.3
      ? "bg-green-500/15 text-green-700 dark:text-green-400"
      : heatmap.fragility_score <= 0.6
        ? "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400"
        : "bg-red-500/15 text-red-700 dark:text-red-400"
  const label = `Retention ${Math.round(retentionPct)}%`
  return (
    <span
      title={`${label}${heatmap.due_card_count > 0 ? ` | ${heatmap.due_card_count} due` : ""}`}
      className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums ${tone}`}
    >
      {Math.round(retentionPct)}%
      {heatmap.due_card_count > 0 && (
        <span className="ml-1 opacity-70">·{heatmap.due_card_count}</span>
      )}
    </span>
  )
}

function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ""
  const diffMs = Date.now() - then
  const min = Math.round(diffMs / 60_000)
  if (min < 1) return "just now"
  if (min < 60) return `${min}m ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr}h ago`
  const d = Math.round(hr / 24)
  if (d < 30) return `${d}d ago`
  const mo = Math.round(d / 30)
  if (mo < 12) return `${mo}mo ago`
  const y = Math.round(mo / 12)
  return `${y}y ago`
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
      const res = await fetch(`${API_BASE}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: documentId,
          section_id: sectionId,
          content,
          tags,
          group_name: null,
        }),
      })
      if (!res.ok) throw new Error(`Failed to create note: ${res.status}`)
      onSaved()
    } catch {
      setSaveError("Failed to save note. Please try again.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-2 flex flex-col gap-2 rounded-md border border-primary/40 bg-background p-2">
      {saveError && <p className="text-xs text-destructive">{saveError}</p>}
      <textarea
        autoFocus
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Write a note..."
        className="min-h-[72px] w-full resize-none bg-transparent text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
      />
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

interface SectionListItemProps {
  section: SectionItem
  isAudio: boolean
  isVideo: boolean
  isYouTube: boolean
  doc: { id: string; format?: string; source_url?: string | null }
  hasNote: boolean
  editorOpen: boolean
  heatmapItem: SectionHeatmapItem | null
  searchHit: boolean
  searchSnippet?: string
  progressPct?: number
  annotations: AnnotationItem[]
  feynmanEnabled: boolean
  isActive: boolean
  lastPracticedAt?: string
  childCount: number
  isCollapsed: boolean
  onToggleCollapsed: (id: string) => void
  onRead: (id: string) => void
  onPdfJump: (p: number) => void
  onMediaJump: (t: number) => void
  onToggleNote: (id: string) => void
  onSaved: () => void
  onCancel: () => void
  onFeynman: (id: string) => void
  onPrefetchFeynman: (id: string) => void
  onShowGoals: (id: string) => void
}

// Memoized so unrelated state changes (e.g. PDF current page) don't re-render
// every section in a 1000-section list.
export const SectionListItem = memo(({
  section,
  isAudio,
  isVideo,
  isYouTube,
  doc,
  hasNote,
  editorOpen,
  heatmapItem,
  searchHit,
  searchSnippet,
  progressPct,
  annotations,
  feynmanEnabled,
  isActive,
  lastPracticedAt,
  childCount,
  isCollapsed,
  onToggleCollapsed,
  onRead,
  onPdfJump,
  onMediaJump,
  onToggleNote,
  onSaved,
  onCancel,
  onFeynman,
  onPrefetchFeynman,
  onShowGoals,
}: SectionListItemProps) => {
  const fragilityClass = fragilityBorderClass(heatmapItem?.fragility_score ?? null)
  const sectionBorderClass = section.admonition_type
    ? admonitionClass(section.admonition_type)
    : fragilityClass

  const tooltipText = heatmapItem?.fragility_score != null
    ? `Fragility: ${Math.round(heatmapItem.fragility_score * 100)}% | Due: ${heatmapItem.due_card_count}`
    : section.heading

  const mediaStartTime = (isAudio || isVideo || isYouTube) ? parseAudioStartTime(section.heading) : null

  const headingNode = (
    <span className="min-w-0 flex-1 truncate">
      {section.admonition_type && (
        <span
          className="mr-1 rounded px-1 py-0.5 text-[10px] font-bold uppercase tracking-wide"
          style={{ color: ADMONITION_LABEL_COLORS[section.admonition_type] ?? "inherit" }}
        >
          {section.admonition_type}
        </span>
      )}
      {section.heading || "(Untitled section)"}
    </span>
  )

  const lastPracticedLabel = lastPracticedAt ? formatRelativeTime(lastPracticedAt) : null

  return (
    <li
      data-section-id={section.id}
      title={tooltipText}
      className={cn(
        "group rounded-md border p-3 min-h-[50px] transition-colors",
        isActive
          ? "border-primary/50 bg-primary/5"
          : "border-border hover:border-border/80 hover:bg-muted/40",
        section.admonition_type && sectionBorderClass,
        searchHit && "ring-2 ring-primary",
      )}
    >
      <div
        className="flex items-center gap-2 text-sm font-semibold text-foreground"
        style={{ paddingLeft: `${Math.max(0, section.level - 1) * 12}px` }}
      >
        {childCount > 0 ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onToggleCollapsed(section.id)
            }}
            title={isCollapsed ? `Expand ${childCount} subsections` : "Collapse subsections"}
            className="-ml-1 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            {isCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
          </button>
        ) : (
          <span className="-ml-1 inline-block w-[18px] shrink-0" aria-hidden />
        )}
        <button
          type="button"
          onClick={() => onRead(section.id)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left hover:text-primary"
          title="Read this section"
        >
          {headingNode}
        </button>
        {isCollapsed && childCount > 0 && (
          <span
            className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground"
            title={`${childCount} hidden subsections`}
          >
            +{childCount}
          </span>
        )}
        <RetentionChip heatmap={heatmapItem} />
        {progressPct !== undefined && (
          <button
            onClick={() => onShowGoals(section.id)}
            title={`${Math.round(progressPct)}% objectives covered`}
            className="shrink-0"
          >
            <ChapterProgressRing pct={progressPct} size={12} />
          </button>
        )}
        {hasNote && (
          <span title="Has note" className="shrink-0 text-primary">
            <StickyNote size={12} />
          </span>
        )}
      </div>

      {(lastPracticedLabel || mediaStartTime !== null || (doc.format === "pdf" && section.page_start > 0)) && (
        <div
          className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground"
          style={{ paddingLeft: `${Math.max(0, section.level - 1) * 12}px` }}
        >
          {lastPracticedLabel && (
            <span className="inline-flex items-center gap-1">
              <Brain size={10} />
              <span>Practiced {lastPracticedLabel}</span>
            </span>
          )}
          {doc.format === "pdf" && section.page_start > 0 && (
            <button
              onClick={() => onPdfJump(section.page_start)}
              title={`Open PDF at page ${section.page_start}`}
              className="tabular-nums hover:text-foreground"
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
                className="tabular-nums hover:text-foreground"
              >
                {formatMmSs(mediaStartTime)}
              </a>
            ) : (
              <button
                onClick={() => onMediaJump(mediaStartTime)}
                title={`Play from ${formatMmSs(mediaStartTime)}`}
                className="tabular-nums hover:text-foreground"
              >
                {formatMmSs(mediaStartTime)}
              </button>
            )
          )}
        </div>
      )}

      <div
        className="mt-2 flex flex-wrap items-center gap-1.5"
        style={{ paddingLeft: `${Math.max(0, section.level - 1) * 12}px` }}
      >
        <button
          onClick={() => onRead(section.id)}
          title="Read from this section"
          className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-[11px] font-medium text-muted-foreground hover:border-primary/50 hover:text-foreground"
        >
          <BookOpen size={11} />
          <span>Read</span>
        </button>
        {feynmanEnabled && (
          <button
            onClick={() => onFeynman(section.id)}
            onMouseEnter={() => onPrefetchFeynman(section.id)}
            onFocus={() => onPrefetchFeynman(section.id)}
            title="Explain this section in your own words (Feynman technique)"
            className="inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary hover:bg-primary/20"
          >
            <Brain size={11} />
            <span>Practice</span>
          </button>
        )}
        <button
          onClick={() => onToggleNote(section.id)}
          title={hasNote ? "Edit note" : "Add note"}
          className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-[11px] font-medium text-muted-foreground hover:border-primary/50 hover:text-foreground"
        >
          <StickyNote size={11} />
          <span>{hasNote ? "Note" : "Note"}</span>
        </button>
      </div>

      {section.preview && (
        <SectionPreviewWithHighlights
          preview={section.preview}
          annotations={annotations}
          sectionId={section.id}
          searchSnippet={searchSnippet}
        />
      )}
      {section.preview && hasCodeFence(section.preview) && (
        <PredictPanel
          sectionId={section.id}
          documentId={doc.id}
          preview={section.preview}
        />
      )}
      {editorOpen && (
        <NoteEditor
          documentId={doc.id}
          sectionId={section.id}
          onSaved={onSaved}
          onCancel={onCancel}
        />
      )}
    </li>
  )
})
SectionListItem.displayName = "SectionListItem"
