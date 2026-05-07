import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { cn } from "@/lib/utils"
import { isDocumentErrored, isDocumentProcessing } from "@/lib/documentReadiness"
import { 
  Book, 
  BookOpen, 
  Bookmark, 
  Check, 
  Code, 
  Cpu, 
  FileText, 
  MessageSquare, 
  Mic, 
  MoreVertical, 
  Network, 
  Newspaper, 
  Pencil, 
  StickyNote, 
  Trash2, 
  X, 
  Zap 
} from "lucide-react"
import { useEffect, useRef, useState } from "react"
import type { DocAction } from "@/lib/docActionUtils"
import { DOC_ACTIONS } from "@/lib/docActionUtils"
import type { ContentType, DocumentListItem } from "./types"
import {
  CONTENT_TYPE_ICONS,
  Youtube,
  STATUS_LABELS,
  STATUS_VARIANTS,
  formatDuration,
  formatWordCount,
  isYouTubeDoc,
  relativeDate,
} from "./utils"

import { API_BASE } from "@/lib/config"

function ProgressRing({ pct, size = 24 }: { pct: number; size?: number }) {
  const r = (size - 4) / 2
  const circ = 2 * Math.PI * r
  const dashOffset = circ - (pct / 100) * circ
  return (
    <svg width={size} height={size} className="shrink-0" aria-hidden="true">
      <circle
        cx={size / 2} cy={size / 2} r={r}
        fill="none" stroke="currentColor" strokeWidth={2}
        className="text-muted/30"
      />
      <circle
        cx={size / 2} cy={size / 2} r={r}
        fill="none" stroke="currentColor" strokeWidth={2}
        strokeDasharray={circ} strokeDashoffset={dashOffset}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        className="text-primary"
      />
    </svg>
  )
}

const CONTENT_TYPE_BADGE: Record<ContentType, { label: string; className: string; icon: typeof Book }> = {
  book: { label: "Book", className: "bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100", icon: Book },
  conversation: { label: "Chat Log", className: "bg-green-50 text-green-700 border-green-200 hover:bg-green-100", icon: MessageSquare },
  notes: { label: "Note", className: "bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100", icon: StickyNote },
  paper: { label: "Paper", className: "bg-purple-50 text-purple-700 border-purple-200 hover:bg-purple-100", icon: FileText },
  code: { label: "Code", className: "bg-orange-50 text-orange-700 border-orange-200 hover:bg-orange-100", icon: Code },
  audio: { label: "Audio", className: "bg-yellow-50 text-yellow-700 border-yellow-200 hover:bg-yellow-100", icon: Mic },
  epub: { label: "E-Book", className: "bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100", icon: BookOpen },
  kindle_clippings: { label: "Kindle", className: "bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100", icon: Bookmark },
  tech_book: { label: "Tech Book", className: "bg-cyan-50 text-cyan-700 border-cyan-200 hover:bg-cyan-100", icon: Cpu },
  tech_article: { label: "Article", className: "bg-teal-50 text-teal-700 border-teal-200 hover:bg-teal-100", icon: Newspaper },
}

const YOUTUBE_BADGE = { label: "YouTube", className: "bg-red-100 text-red-700 hover:bg-red-200" }
const KINDLE_SOURCE_BADGE = { label: "Kindle", className: "bg-amber-100 text-amber-700 hover:bg-amber-200" }

// Accent band colors per content type (top-border gradient effect)
const ACCENT_COLORS: Record<string, string> = {
  book: "from-indigo-500 to-blue-500",
  paper: "from-purple-500 to-violet-500",
  code: "from-orange-500 to-amber-500",
  epub: "from-indigo-400 to-purple-500",
  conversation: "from-emerald-500 to-green-500",
  notes: "from-slate-400 to-gray-500",
  audio: "from-yellow-500 to-orange-400",
  kindle_clippings: "from-amber-500 to-yellow-500",
  tech_book: "from-blue-500 to-cyan-500",
  tech_article: "from-teal-500 to-emerald-500",
  youtube: "from-red-500 to-rose-500",
}

const CHANGEABLE_TYPES: ContentType[] = ["book", "conversation", "notes", "tech_book", "tech_article"]

const ACTION_ICONS: Record<DocAction, typeof BookOpen> = {
  read: BookOpen,
  chat: MessageSquare,
  study: Zap,
  notes: StickyNote,
  viz: Network,
}

interface DocumentCardProps {
  doc: DocumentListItem
  onClick: (id: string) => void
  onTagClick?: (tag: string) => void
  onTagsChange?: (id: string, tags: string[]) => void
  onDelete?: (id: string) => void
  onContentTypeChange?: (id: string, contentType: ContentType) => void
  onAction?: (docId: string, action: DocAction) => void
  selected?: boolean
  onSelect?: (id: string, selected: boolean) => void
  selectMode?: boolean
}

export function DocumentCard({
  doc,
  onClick,
  onTagClick,
  onTagsChange,
  onDelete,
  onContentTypeChange,
  onAction,
  selected = false,
  onSelect,
  selectMode = false,
}: DocumentCardProps) {
  const isYouTube = isYouTubeDoc(doc)
  const isKindleSource = doc.tags.includes("kindle")
  const Icon = isYouTube ? Youtube : CONTENT_TYPE_ICONS[doc.content_type]
  const isProcessing = isDocumentProcessing(doc)
  const isErrored = isDocumentErrored(doc)
  const badge = isYouTube ? { ...YOUTUBE_BADGE, icon: Youtube } : (isKindleSource ? { ...KINDLE_SOURCE_BADGE, icon: Bookmark } : CONTENT_TYPE_BADGE[doc.content_type])
  const [editingTags, setEditingTags] = useState(false)
  const [tagInput, setTagInput] = useState("")
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [typePopoverOpen, setTypePopoverOpen] = useState(false)
  const popoverRef = useRef<HTMLDivElement>(null)
  const [actionMenuOpen, setActionMenuOpen] = useState(false)
  const actionMenuRef = useRef<HTMLDivElement>(null)

  // Close popover on outside click
  useEffect(() => {
    if (!typePopoverOpen && !actionMenuOpen) return
    function handleClick(e: MouseEvent) {
      if (typePopoverOpen && popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setTypePopoverOpen(false)
      }
      if (actionMenuOpen && actionMenuRef.current && !actionMenuRef.current.contains(e.target as Node)) {
        setActionMenuOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [typePopoverOpen, actionMenuOpen])

  function handleCardClick(e: React.MouseEvent) {
    if (selectMode && onSelect) {
      e.preventDefault()
      onSelect(doc.id, !selected)
      return
    }
    onClick(doc.id)
  }

  function handleCheckboxChange(e: React.ChangeEvent<HTMLInputElement>) {
    e.stopPropagation()
    onSelect?.(doc.id, e.target.checked)
  }

  function handleTagEdit(e: React.MouseEvent) {
    e.stopPropagation()
    setEditingTags(true)
    setTagInput("")
  }

  function handleTagRemove(e: React.MouseEvent, tag: string) {
    e.stopPropagation()
    onTagsChange?.(doc.id, doc.tags.filter((t) => t !== tag))
  }

  function handleTagInputKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && tagInput.trim()) {
      e.preventDefault()
      const newTag = tagInput.trim().toLowerCase()
      if (!doc.tags.includes(newTag)) {
        onTagsChange?.(doc.id, [...doc.tags, newTag])
      }
      setTagInput("")
    } else if (e.key === "Escape") {
      setEditingTags(false)
    }
  }

  function handleTagInputClick(e: React.MouseEvent) {
    e.stopPropagation()
  }

  function handleCommitTags(e: React.MouseEvent) {
    e.stopPropagation()
    setEditingTags(false)
  }

  async function handleTypeChange(newType: ContentType) {
    setTypePopoverOpen(false)
    if (newType === doc.content_type) return
    try {
      await fetch(`${API_BASE}/documents/${doc.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content_type: newType }),
      })
      onContentTypeChange?.(doc.id, newType)
    } catch {
      // Non-fatal — UI will revert on next query invalidation
    }
  }

  const accentKey = isYouTube ? "youtube" : doc.content_type
  const accentGradient = ACCENT_COLORS[accentKey] ?? "from-slate-400 to-gray-500"

  return (
    <Card
      className={cn(
        "group cursor-pointer select-none transition-all duration-200 overflow-hidden",
        "hover:shadow-lg hover:-translate-y-0.5",
        selected ? "border-primary bg-primary/5 ring-1 ring-primary/30" : "hover:border-border/80",
        isProcessing && "opacity-70",
        isErrored && "border-red-200",
      )}
      onClick={handleCardClick}
      title={
        isProcessing
          ? "Document is still being ingested. Open it to see live progress."
          : isErrored
          ? "Ingestion failed. Open the card to retry or delete."
          : undefined
      }
    >
      {/* Accent band */}
      <div className={cn("h-1 w-full bg-gradient-to-r", accentGradient)} />
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {onSelect && (
            <input
              type="checkbox"
              checked={selected}
              onChange={handleCheckboxChange}
              onClick={(e) => e.stopPropagation()}
              className="shrink-0 h-4 w-4 rounded border-border accent-primary"
            />
          )}
          <Icon size={16} className="shrink-0 text-muted-foreground" />
          <h3 className="truncate text-sm font-semibold text-foreground">{doc.title}</h3>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {isProcessing ? (
            <span className="rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
              Processing…
            </span>
          ) : isErrored ? (
            <span className="rounded-full border border-red-300 bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">
              Failed
            </span>
          ) : (
            <Badge variant={STATUS_VARIANTS[doc.learning_status]}>
              {STATUS_LABELS[doc.learning_status]}
            </Badge>
          )}
          {/* S191: Document action menu */}
          {onAction && !selectMode && (
            <div className="relative" ref={actionMenuRef}>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setActionMenuOpen((v) => !v)
                }}
                className="sm:opacity-0 sm:group-hover:opacity-100 transition-opacity rounded p-0.5 text-muted-foreground hover:text-foreground hover:bg-accent"
                title="Actions"
              >
                <MoreVertical size={14} />
              </button>
              {actionMenuOpen && (
                <div
                  className="absolute right-0 top-full z-30 mt-1 w-48 rounded-lg border border-border bg-background p-1 shadow-lg"
                  onClick={(e) => e.stopPropagation()}
                >
                  {DOC_ACTIONS.map(({ action, label }) => {
                    const ActionIcon = ACTION_ICONS[action]
                    return (
                      <button
                        key={action}
                        onClick={() => {
                          setActionMenuOpen(false)
                          onAction(doc.id, action)
                        }}
                        className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent"
                      >
                        <ActionIcon size={14} className="shrink-0 text-muted-foreground" />
                        {label}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          )}
          {onDelete && !selectMode && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                setConfirmDelete(true)
              }}
              className="opacity-0 group-hover:opacity-100 transition-opacity rounded p-0.5 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
              title={`Delete ${doc.title}`}
            >
              <Trash2 size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Content type badge */}
      <div className="mt-1.5 relative inline-block" ref={popoverRef}>
        <button
          onClick={(e) => {
            e.stopPropagation()
            setTypePopoverOpen((v) => !v)
          }}
          title="Change document type (re-ingest to apply new chunking)"
          className={cn(
            "flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider transition-colors border shadow-sm",
            badge.className,
          )}
        >
          {badge.icon && <badge.icon size={10} />}
          {badge.label}
        </button>

        {typePopoverOpen && (
          <div
            className="absolute left-0 top-full z-20 mt-1 w-52 rounded-lg border border-border bg-background p-2 shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <p className="mb-1.5 px-1 text-xs text-muted-foreground">
              Re-ingest document to apply new chunking strategy.
            </p>
            {CHANGEABLE_TYPES.map((t) => {
              const opt = CONTENT_TYPE_BADGE[t]
              return (
                <button
                  key={t}
                  onClick={() => void handleTypeChange(t)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent",
                    doc.content_type === t && "font-medium",
                  )}
                >
                  {doc.content_type === t && <Check size={12} className="shrink-0 text-primary" />}
                  {doc.content_type !== t && <span className="w-3" />}
                  {opt.label}
                </button>
              )
            })}
          </div>
        )}
      </div>

      <div className="mt-1.5 flex items-center gap-2 text-xs text-muted-foreground">
        <span>{formatWordCount(doc.word_count)}</span>
        <span>·</span>
        <span>{relativeDate(doc.created_at)}</span>
        {doc.audio_duration_seconds != null && (
          <>
            <span>·</span>
            <span>{formatDuration(doc.audio_duration_seconds)}</span>
          </>
        )}
      </div>

      {doc.enrichment_status && (
        <span className={cn(
          "mt-1.5 inline-block rounded-full px-2 py-0.5 text-xs",
          (doc.enrichment_status === "pending" || doc.enrichment_status === "running") && "animate-pulse bg-blue-100 text-blue-600",
          doc.enrichment_status === "done" && "bg-green-100 text-green-700",
          doc.enrichment_status === "failed" && "bg-orange-100 text-orange-700",
        )}>
          {(doc.enrichment_status === "pending" || doc.enrichment_status === "running") && "Enriching..."}
          {doc.enrichment_status === "done" && (
            (doc.format === "pdf" || doc.format === "epub" || doc.format === "md" || doc.format === "markdown") ? "Images ready" : "Analysis complete"
          )}
          {doc.enrichment_status === "failed" && "Enrichment failed"}
        </span>
      )}

      {doc.summary_one_sentence && (
        <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
          {doc.summary_one_sentence}
        </p>
      )}

      {doc.flashcard_count > 0 && (
        <p className="mt-1 text-xs text-muted-foreground">
          {doc.flashcard_count} flashcard{doc.flashcard_count !== 1 ? "s" : ""}
        </p>
      )}

      {/* Tags row */}
      <div className="mt-2 flex flex-wrap items-center gap-1.5 min-h-[22px]">
        {doc.tags.map((tag) => (
          <button
            key={tag}
            onClick={(e) => {
              e.stopPropagation()
              onTagClick?.(tag)
            }}
            className="flex items-center gap-0.5 rounded-full bg-accent px-2 py-0.5 text-xs text-accent-foreground hover:bg-primary/20 transition-colors"
          >
            {tag}
            {editingTags && (
              <X
                size={10}
                className="ml-0.5 text-muted-foreground hover:text-destructive"
                onClick={(e) => handleTagRemove(e, tag)}
              />
            )}
          </button>
        ))}

        {editingTags ? (
          <div className="flex items-center gap-1" onClick={handleTagInputClick}>
            <input
              autoFocus
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={handleTagInputKeyDown}
              placeholder="add tag..."
              className="h-5 w-20 rounded border border-border bg-background px-1.5 text-xs outline-none focus:border-primary"
            />
            <button onClick={handleCommitTags} className="text-primary hover:text-primary/80">
              <Check size={12} />
            </button>
          </div>
        ) : (
          onTagsChange && (
            <button
              onClick={handleTagEdit}
              className="text-muted-foreground/60 hover:text-muted-foreground transition-colors"
              title="Edit tags"
            >
              <Pencil size={11} />
            </button>
          )
        )}
      </div>

      {/* Reading progress bar — shown when at least one section has been read */}
      {doc.reading_progress_pct > 0 && (
        <div className="mt-2">
          <Progress value={doc.reading_progress_pct * 100} className="h-1" />
        </div>
      )}

      {/* Objective progress ring (S143) — shown only when objectives have been extracted */}
      {doc.objective_progress_pct !== null && (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <ProgressRing pct={doc.objective_progress_pct} size={24} />
          <span>{Math.round(doc.objective_progress_pct)}% objectives covered</span>
        </div>
      )}

      {/* Inline delete confirmation */}
      {confirmDelete && (
        <div
          className="mt-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2"
          onClick={(e) => e.stopPropagation()}
        >
          <p className="text-xs text-foreground mb-2">
            Delete <span className="font-semibold">{doc.title}</span>?
            {isProcessing
              ? " The in-flight ingestion will be cancelled."
              : " This cannot be undone."}
          </p>
          <div className="flex justify-end gap-2">
            <button
              onClick={(e) => {
                e.stopPropagation()
                setConfirmDelete(false)
              }}
              className="rounded border border-border px-2.5 py-1 text-xs hover:bg-accent"
            >
              Cancel
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation()
                setConfirmDelete(false)
                onDelete?.(doc.id)
              }}
              className="rounded bg-destructive px-2.5 py-1 text-xs font-medium text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </button>
          </div>
        </div>
      )}
    </Card>
  )
}
