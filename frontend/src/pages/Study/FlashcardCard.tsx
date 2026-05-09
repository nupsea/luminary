// FlashcardCard -- a single flashcard tile with flip animation, edit
// mode, delete confirmation, and a footer of FSRS / Bloom badges.
//
// Pure UI: state is local (showAnswer / editing / confirmDelete +
// edit field buffers), mutations are passed in via callbacks. No
// fetches, no store reads.

import { useState } from "react"
import {
  Check,
  ChevronDown,
  ChevronUp,
  Loader2,
  Pencil,
  Trash2,
  X,
} from "lucide-react"
import { AnimatePresence, motion } from "framer-motion"

import { Card } from "@/components/ui/card"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"

import type { Flashcard } from "./types"

interface FlashcardCardProps {
  card: Flashcard
  onUpdate: (id: string, data: { question?: string; answer?: string }) => void
  onDelete: (id: string) => void
  isUpdating: boolean
  isDeleting: boolean
  selectionMode?: boolean
  selected?: boolean
  onToggleSelect?: (id: string) => void
}

export function FlashcardCard({
  card,
  onUpdate,
  onDelete,
  isUpdating,
  isDeleting,
  selectionMode = false,
  selected = false,
  onToggleSelect,
}: FlashcardCardProps) {
  const [showAnswer, setShowAnswer] = useState(false)
  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [editQuestion, setEditQuestion] = useState(card.question)
  const [editAnswer, setEditAnswer] = useState(card.answer)

  function handleEditSave() {
    onUpdate(card.id, { question: editQuestion, answer: editAnswer })
    setEditing(false)
  }

  function handleEditCancel() {
    setEditQuestion(card.question)
    setEditAnswer(card.answer)
    setEditing(false)
  }

  return (
    <Card
      className={`flex flex-col gap-3 ${selected ? "ring-2 ring-primary" : ""}`}
    >
      {selectionMode && (
        <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelect?.(card.id)}
            className="h-4 w-4 rounded border-border text-primary focus:ring-primary"
          />
          Select for bulk delete
        </label>
      )}
      {/* S188: Section heading label */}
      {card.section_heading && !editing && (
        <p className="text-xs text-muted-foreground">{card.section_heading}</p>
      )}
      {/* Flip container */}
      <div className="relative w-full mt-2 min-h-[140px]" style={{ perspective: "1000px" }}>
        <AnimatePresence mode="wait">
          {/* Front (Question only) */}
          {!editing && !showAnswer && (
            <motion.div
              key="front"
              initial={{ rotateX: -180, opacity: 0 }}
              animate={{ rotateX: 0, opacity: 1 }}
              exit={{ rotateX: 180, opacity: 0 }}
              transition={{ duration: 0.4, ease: "easeInOut" }}
              style={{ backfaceVisibility: "hidden" }}
              className="w-full flex flex-col gap-2"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="flex-1 text-sm font-medium text-foreground">{card.question}</p>
                {!confirmDelete && (
                  <div className="flex shrink-0 gap-1">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setEditing(true)
                      }}
                      className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                      title="Edit"
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setConfirmDelete(true)
                      }}
                      className="rounded p-1 text-muted-foreground hover:bg-red-50 hover:text-red-600"
                      title="Delete"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                )}
              </div>
              <div>
                <button
                  onClick={() => setShowAnswer(true)}
                  className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 mt-1"
                >
                  <ChevronDown size={12} /> Make it flip
                </button>
              </div>
            </motion.div>
          )}

          {/* Back (Question + Answer) */}
          {!editing && showAnswer && (
            <motion.div
              key="back"
              initial={{ rotateX: 180, opacity: 0 }}
              animate={{ rotateX: 0, opacity: 1 }}
              exit={{ rotateX: -180, opacity: 0 }}
              transition={{ duration: 0.4, ease: "easeInOut" }}
              style={{ backfaceVisibility: "hidden" }}
              className="w-full flex flex-col gap-2 rounded-lg border border-primary/20 bg-primary/5 p-3"
            >
              <p className="text-sm font-medium text-muted-foreground">{card.question}</p>
              <hr className="border-primary/10" />
              <MarkdownRenderer className="text-sm text-foreground">{card.answer}</MarkdownRenderer>
              <button
                onClick={() => setShowAnswer(false)}
                className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 mt-2 self-start"
              >
                <ChevronUp size={12} /> Hide answer
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Editing mode */}
        {editing && (
          <div className="flex flex-col gap-3">
            <textarea
              value={editQuestion}
              onChange={(e) => setEditQuestion(e.target.value)}
              className="resize-none rounded border border-border bg-background p-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              rows={2}
              placeholder="Question..."
            />
            <textarea
              value={editAnswer}
              onChange={(e) => setEditAnswer(e.target.value)}
              className="resize-none rounded border border-border bg-background p-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              rows={3}
              placeholder="Answer..."
            />
          </div>
        )}
      </div>
      {editing && (
        <div className="flex gap-2">
          <button
            onClick={handleEditSave}
            disabled={isUpdating}
            className="flex items-center gap-1 rounded bg-primary px-3 py-1 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {isUpdating ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
            Save
          </button>
          <button
            onClick={handleEditCancel}
            className="flex items-center gap-1 rounded border border-border px-3 py-1 text-xs text-muted-foreground hover:bg-accent"
          >
            <X size={12} />
            Cancel
          </button>
        </div>
      )}

      {/* Delete confirmation */}
      {confirmDelete && (
        <div className="flex items-center gap-2 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-700">
          <span className="flex-1">Delete this flashcard?</span>
          <button
            onClick={() => {
              onDelete(card.id)
              setConfirmDelete(false)
            }}
            disabled={isDeleting}
            className="flex items-center gap-1 rounded bg-red-600 px-2 py-1 text-white hover:bg-red-700 disabled:opacity-50"
          >
            {isDeleting ? <Loader2 size={10} className="animate-spin" /> : null}
            Delete
          </button>
          <button
            onClick={() => setConfirmDelete(false)}
            className="rounded border border-red-300 px-2 py-1 hover:bg-red-100"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Footer: FSRS state badge + Bloom type/level badges */}
      <div className="flex items-center gap-2 border-t border-border pt-2 flex-wrap">
        <span className="rounded-full bg-secondary px-2 py-0.5 text-xs text-secondary-foreground capitalize">
          {card.fsrs_state}
        </span>
        {card.flashcard_type && (
          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-700 capitalize">
            {card.flashcard_type.replace(/_/g, " ")}
          </span>
        )}
        {card.bloom_level != null && (
          <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs text-purple-700">
            L{card.bloom_level}
          </span>
        )}
        {card.is_user_edited && (
          <span className="text-xs text-muted-foreground italic">edited</span>
        )}
        <span className="ml-auto text-xs text-muted-foreground">
          {card.reps} rep{card.reps !== 1 ? "s" : ""}
        </span>
      </div>
    </Card>
  )
}
