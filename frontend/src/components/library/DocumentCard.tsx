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
  Film,
  FolderPlus,
  MessageSquare,
  Sparkles,
  Mic, 
  MoreVertical,
  Network,
  Newspaper,
  StickyNote,
  Trash2, 
  X, 
  Zap 
} from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import type { DocAction } from "@/lib/docActionUtils"
import { DOC_ACTIONS } from "@/lib/docActionUtils"
import { isSurfaceVisible } from "@/lib/surfaceManifest"
import { addDocumentToCollection, fetchCollectionTree } from "@/lib/notesApi"
import { retagDocument } from "@/pages/Learning/api"
import { flattenCollectionTree, type CollectionTreeItem } from "@/lib/collectionUtils"
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

import { apiPatch } from "@/lib/apiClient"

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
  book: { label: "Book", className: "bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-900 dark:hover:bg-blue-900/50", icon: Book },
  conversation: { label: "Chat Log", className: "bg-green-50 text-green-700 border-green-200 hover:bg-green-100 dark:bg-green-950/40 dark:text-green-300 dark:border-green-900 dark:hover:bg-green-900/50", icon: MessageSquare },
  notes: { label: "Note", className: "bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100 dark:bg-slate-800/60 dark:text-slate-300 dark:border-slate-700 dark:hover:bg-slate-800", icon: StickyNote },
  paper: { label: "Paper", className: "bg-purple-50 text-purple-700 border-purple-200 hover:bg-purple-100 dark:bg-purple-950/40 dark:text-purple-300 dark:border-purple-900 dark:hover:bg-purple-900/50", icon: FileText },
  code: { label: "Code", className: "bg-orange-50 text-orange-700 border-orange-200 hover:bg-orange-100 dark:bg-orange-950/40 dark:text-orange-300 dark:border-orange-900 dark:hover:bg-orange-900/50", icon: Code },
  audio: { label: "Audio", className: "bg-yellow-50 text-yellow-700 border-yellow-200 hover:bg-yellow-100 dark:bg-yellow-950/40 dark:text-yellow-300 dark:border-yellow-900 dark:hover:bg-yellow-900/50", icon: Mic },
  epub: { label: "E-Book", className: "bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100 dark:bg-indigo-950/40 dark:text-indigo-300 dark:border-indigo-900 dark:hover:bg-indigo-900/50", icon: BookOpen },
  kindle_clippings: { label: "Kindle", className: "bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900 dark:hover:bg-amber-900/50", icon: Bookmark },
  tech_book: { label: "Tech Book", className: "bg-cyan-50 text-cyan-700 border-cyan-200 hover:bg-cyan-100 dark:bg-cyan-950/40 dark:text-cyan-300 dark:border-cyan-900 dark:hover:bg-cyan-900/50", icon: Cpu },
  tech_article: { label: "Article", className: "bg-teal-50 text-teal-700 border-teal-200 hover:bg-teal-100 dark:bg-teal-950/40 dark:text-teal-300 dark:border-teal-900 dark:hover:bg-teal-900/50", icon: Newspaper },
  technical: { label: "Technical", className: "bg-cyan-50 text-cyan-700 border-cyan-200 hover:bg-cyan-100 dark:bg-cyan-950/40 dark:text-cyan-300 dark:border-cyan-900 dark:hover:bg-cyan-900/50", icon: Cpu },
  video: { label: "Video", className: "bg-rose-50 text-rose-700 border-rose-200 hover:bg-rose-100 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-900 dark:hover:bg-rose-900/50", icon: Film },
}

const YOUTUBE_BADGE = { label: "YouTube", className: "bg-red-100 text-red-700 hover:bg-red-200 dark:bg-red-950/40 dark:text-red-300 dark:hover:bg-red-900/50" }
const KINDLE_SOURCE_BADGE = { label: "Kindle", className: "bg-amber-100 text-amber-700 hover:bg-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:hover:bg-amber-900/50" }

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
  technical: "from-blue-500 to-cyan-500",
  video: "from-rose-500 to-pink-500",
  youtube: "from-red-500 to-rose-500",
}

const CHANGEABLE_TYPES: ContentType[] = ["book", "conversation", "notes", "paper", "tech_book", "tech_article"]

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
  const navigate = useNavigate()
  // "View in graph" only makes sense when the Map surface ships in this build;
  // it's trimmed from public bundles, so drop the action there.
  const visibleActions = DOC_ACTIONS.filter(
    ({ action }) => action !== "viz" || isSurfaceVisible("map"),
  )
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [typePopoverOpen, setTypePopoverOpen] = useState(false)
  const popoverRef = useRef<HTMLDivElement>(null)
  const [actionMenuOpen, setActionMenuOpen] = useState(false)
  const actionMenuRef = useRef<HTMLDivElement>(null)
  const [collectionPickerOpen, setCollectionPickerOpen] = useState(false)
  const [collections, setCollections] = useState<CollectionTreeItem[] | null>(null)
  const [collectionsLoading, setCollectionsLoading] = useState(false)
  const [addedCollectionIds, setAddedCollectionIds] = useState<Set<string>>(new Set())
  const [retagState, setRetagState] = useState<"idle" | "running" | "done">("idle")
  const [retagAdded, setRetagAdded] = useState<number | null>(null)

  // Close popover on outside click
  useEffect(() => {
    if (!typePopoverOpen && !actionMenuOpen) return
    function handleClick(e: MouseEvent) {
      if (typePopoverOpen && popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setTypePopoverOpen(false)
      }
      if (actionMenuOpen && actionMenuRef.current && !actionMenuRef.current.contains(e.target as Node)) {
        setActionMenuOpen(false)
        setCollectionPickerOpen(false)
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

  async function handleOpenCollectionPicker() {
    setCollectionPickerOpen(true)
    if (collections !== null || collectionsLoading) return
    setCollectionsLoading(true)
    try {
      const tree = await fetchCollectionTree()
      setCollections(tree)
    } finally {
      setCollectionsLoading(false)
    }
  }

  async function handleAddToCollection(collectionId: string) {
    if (addedCollectionIds.has(collectionId)) return
    try {
      await addDocumentToCollection(collectionId, doc.id)
      setAddedCollectionIds((prev) => new Set(prev).add(collectionId))
    } catch {
      // Silent — POST is idempotent server-side; surface failure only if needed later.
    }
  }

  async function handleRetag() {
    if (retagState === "running") return
    setRetagState("running")
    setRetagAdded(null)
    try {
      const res = await retagDocument(doc.id)
      setRetagAdded(res.added)
      setRetagState("done")
    } catch {
      setRetagState("idle")
    }
  }

  async function handleTypeChange(newType: ContentType) {
    setTypePopoverOpen(false)
    if (newType === doc.content_type) return
    try {
      await apiPatch(`/documents/${doc.id}`, { content_type: newType })
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
      draggable={!selectMode}
      onDragStart={(e) => {
        e.dataTransfer.setData("application/x-luminary-doc-id", doc.id)
        e.dataTransfer.effectAllowed = "copy"
      }}
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
            <span className="rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
              Processing…
            </span>
          ) : isErrored ? (
            <span className="rounded-full border border-red-300 bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">
              Failed
            </span>
          ) : (
            <Badge variant={STATUS_VARIANTS[doc.learning_status]}>
              {STATUS_LABELS[doc.learning_status]}
            </Badge>
          )}
          {/* Document action menu */}
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
                  className="absolute right-0 top-full z-30 mt-1 w-56 rounded-lg border border-border bg-background p-1 shadow-lg"
                  onClick={(e) => e.stopPropagation()}
                >
                  {!collectionPickerOpen && (
                    <>
                      {visibleActions.map(({ action, label }) => {
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
                      <div className="my-1 h-px bg-border" />
                      <button
                        onClick={() => void handleOpenCollectionPicker()}
                        className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent"
                      >
                        <FolderPlus size={14} className="shrink-0 text-muted-foreground" />
                        Add to collection…
                      </button>
                      <button
                        onClick={() => void handleRetag()}
                        disabled={retagState === "running"}
                        className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent disabled:opacity-60"
                      >
                        <Sparkles size={14} className="shrink-0 text-muted-foreground" />
                        {retagState === "running"
                          ? "Re-tagging…"
                          : retagState === "done"
                            ? retagAdded && retagAdded > 0
                              ? `Re-tag (added ${retagAdded})`
                              : "Re-tag (no new tags)"
                            : "Re-tag"}
                      </button>
                    </>
                  )}
                  {collectionPickerOpen && (
                    <div className="flex flex-col">
                      <div className="flex items-center justify-between px-2 py-1 text-xs text-muted-foreground">
                        <span>Add to collection</span>
                        <button
                          onClick={() => setCollectionPickerOpen(false)}
                          className="rounded p-0.5 hover:bg-accent hover:text-foreground"
                          title="Back"
                        >
                          <X size={12} />
                        </button>
                      </div>
                      <div className="max-h-56 overflow-y-auto">
                        {collectionsLoading && (
                          <p className="px-2 py-1.5 text-xs text-muted-foreground">Loading…</p>
                        )}
                        {!collectionsLoading && collections && collections.length === 0 && (
                          <p className="px-2 py-1.5 text-xs text-muted-foreground">No collections yet</p>
                        )}
                        {!collectionsLoading && collections && collections.length > 0 && (
                          flattenCollectionTree(collections).map((col) => {
                            const added = addedCollectionIds.has(col.id)
                            const isChild = !collections.some((root) => root.id === col.id)
                            return (
                              <button
                                key={col.id}
                                onClick={() => void handleAddToCollection(col.id)}
                                disabled={added}
                                className={cn(
                                  "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors",
                                  added ? "text-muted-foreground" : "hover:bg-accent",
                                  isChild && "pl-5",
                                )}
                              >
                                <span
                                  className="h-2 w-2 shrink-0 rounded-sm"
                                  style={{ backgroundColor: col.color }}
                                />
                                <span className="flex-1 truncate">{col.name}</span>
                                {added && <Check size={12} className="shrink-0 text-primary" />}
                              </button>
                            )
                          })
                        )}
                      </div>
                    </div>
                  )}
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
          (doc.enrichment_status === "pending" || doc.enrichment_status === "running") && "animate-pulse bg-blue-100 text-blue-600 dark:bg-blue-950/40 dark:text-blue-300",
          doc.enrichment_status === "done" && "bg-green-100 text-green-700 dark:bg-green-950/40 dark:text-green-300",
          doc.enrichment_status === "failed" && "bg-orange-100 text-orange-700 dark:bg-orange-950/40 dark:text-orange-300",
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
        <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
          <span>{doc.flashcard_count} flashcard{doc.flashcard_count !== 1 ? "s" : ""}</span>
          {doc.mastery_pct !== null && (
            <>
              <span>·</span>
              <span
                className="flex items-center gap-1"
                title={`Mastery: ${doc.mastery_pct}%`}
              >
                <ProgressRing pct={doc.mastery_pct} size={16} />
                <span>{Math.round(doc.mastery_pct)}% mastery</span>
              </span>
            </>
          )}
        </div>
      )}

      {/* Compact tag-count indicator. The full chip cloud + add/remove lives
          in the reader's Tags tab now -- packing 50+ chips into the card
          drowns out the rest of the metadata. */}
      {doc.tags.length > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          {doc.tags.length} tag{doc.tags.length === 1 ? "" : "s"}
        </p>
      )}

      {/* Collection membership chips (plan 2E.5). The add affordance is
          rendered inline whether or not the doc has any collections yet --
          previously discovery relied on the hover-only MoreVertical menu,
          which left users thinking older docs couldn't be added. */}
      <div className="mt-2 flex flex-wrap items-center gap-1">
        {doc.collections?.slice(0, 2).map((c) => (
          <button
            key={c.id}
            onClick={(e) => {
              e.stopPropagation()
              navigate(`/collections/${c.id}`)
            }}
            className="flex items-center gap-1 rounded-full border border-border bg-background px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
            title={`Open collection: ${c.name}`}
          >
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{ backgroundColor: c.color }}
            />
            <span className="truncate max-w-[8rem]">{c.name}</span>
          </button>
        ))}
        {doc.collections && doc.collections.length > 2 && (
          <span
            className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground"
            title={doc.collections
              .slice(2)
              .map((c) => c.name)
              .join(", ")}
          >
            +{doc.collections.length - 2}
          </span>
        )}
        <button
          onClick={(e) => {
            e.stopPropagation()
            // Open the action menu and route straight to the collection
            // picker step so the user lands on the right surface in one
            // click instead of fishing through the action menu.
            setActionMenuOpen(true)
            void handleOpenCollectionPicker()
          }}
          className="flex items-center gap-1 rounded-full border border-dashed border-border bg-background px-2 py-0.5 text-[11px] text-muted-foreground hover:border-primary/40 hover:text-foreground"
          title="Add this document to a collection"
        >
          <FolderPlus size={10} />
          <span>
            {doc.collections && doc.collections.length > 0 ? "Add" : "Add to collection"}
          </span>
        </button>
      </div>

      {/* Reading progress bar — shown when at least one section has been read */}
      {doc.reading_progress_pct > 0 && (
        <div className="mt-2">
          <Progress value={doc.reading_progress_pct * 100} className="h-1" />
        </div>
      )}

      {/* Objective progress ring — shown only when objectives have been extracted */}
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
