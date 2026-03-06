import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import { Check, Pencil, Trash2, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import type { ContentType, DocumentListItem } from "./types"
import {
  CONTENT_TYPE_ICONS,
  STATUS_LABELS,
  STATUS_VARIANTS,
  formatWordCount,
  relativeDate,
} from "./utils"

const API_BASE = "http://localhost:8000"

const CONTENT_TYPE_BADGE: Record<ContentType, { label: string; className: string }> = {
  book: { label: "Book", className: "bg-blue-100 text-blue-700 hover:bg-blue-200" },
  conversation: { label: "Conversation", className: "bg-green-100 text-green-700 hover:bg-green-200" },
  notes: { label: "Notes", className: "bg-gray-100 text-gray-600 hover:bg-gray-200" },
  paper: { label: "Paper", className: "bg-purple-100 text-purple-700 hover:bg-purple-200" },
  code: { label: "Code", className: "bg-orange-100 text-orange-700 hover:bg-orange-200" },
}

const CHANGEABLE_TYPES: ContentType[] = ["book", "conversation", "notes"]

interface DocumentCardProps {
  doc: DocumentListItem
  onClick: (id: string) => void
  onTagClick?: (tag: string) => void
  onTagsChange?: (id: string, tags: string[]) => void
  onDelete?: (id: string) => void
  onContentTypeChange?: (id: string, contentType: ContentType) => void
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
  selected = false,
  onSelect,
  selectMode = false,
}: DocumentCardProps) {
  const Icon = CONTENT_TYPE_ICONS[doc.content_type]
  const [editingTags, setEditingTags] = useState(false)
  const [tagInput, setTagInput] = useState("")
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [typePopoverOpen, setTypePopoverOpen] = useState(false)
  const popoverRef = useRef<HTMLDivElement>(null)

  // Close popover on outside click
  useEffect(() => {
    if (!typePopoverOpen) return
    function handleClick(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setTypePopoverOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [typePopoverOpen])

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

  const badge = CONTENT_TYPE_BADGE[doc.content_type] ?? CONTENT_TYPE_BADGE.notes

  return (
    <Card
      className={`group cursor-pointer select-none transition-colors ${selected ? "border-primary bg-primary/5" : ""}`}
      onClick={handleCardClick}
    >
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
          <Badge variant={STATUS_VARIANTS[doc.learning_status]}>
            {STATUS_LABELS[doc.learning_status]}
          </Badge>
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
            "rounded-full px-2 py-0.5 text-xs font-medium transition-colors",
            badge.className,
          )}
        >
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
      </div>

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

      {/* Inline delete confirmation */}
      {confirmDelete && (
        <div
          className="mt-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2"
          onClick={(e) => e.stopPropagation()}
        >
          <p className="text-xs text-foreground mb-2">
            Delete <span className="font-semibold">{doc.title}</span>? This cannot be undone.
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
