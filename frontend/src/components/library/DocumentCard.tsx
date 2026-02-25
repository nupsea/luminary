import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Check, Pencil, X } from "lucide-react"
import { useState } from "react"
import type { DocumentListItem } from "./types"
import {
  CONTENT_TYPE_ICONS,
  STATUS_LABELS,
  STATUS_VARIANTS,
  formatWordCount,
  relativeDate,
} from "./utils"

interface DocumentCardProps {
  doc: DocumentListItem
  onClick: (id: string) => void
  onTagClick?: (tag: string) => void
  onTagsChange?: (id: string, tags: string[]) => void
  selected?: boolean
  onSelect?: (id: string, selected: boolean) => void
  selectMode?: boolean
}

export function DocumentCard({
  doc,
  onClick,
  onTagClick,
  onTagsChange,
  selected = false,
  onSelect,
  selectMode = false,
}: DocumentCardProps) {
  const Icon = CONTENT_TYPE_ICONS[doc.content_type]
  const [editingTags, setEditingTags] = useState(false)
  const [tagInput, setTagInput] = useState("")

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

  return (
    <Card
      className={`cursor-pointer select-none transition-colors ${selected ? "border-primary bg-primary/5" : ""}`}
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
        <Badge variant={STATUS_VARIANTS[doc.learning_status]}>
          {STATUS_LABELS[doc.learning_status]}
        </Badge>
      </div>

      <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
        <span className="capitalize">{doc.content_type}</span>
        <span>·</span>
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
    </Card>
  )
}
