// NoteCard -- card view of a single note. Editing is delegated to
// NoteEditorDialog (the parent opens it when onEdit fires). The card
// owns the inline delete confirmation and the tag chips that
// dispatch a tag-navigate event for the sidebar tree.

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { BookOpen, FileText, Pencil, Tag, Trash2 } from "lucide-react"
import { useState } from "react"
import { useNavigate } from "react-router-dom"

import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { relativeDate } from "@/components/library/utils"
import { dispatchTagNavigate } from "@/lib/noteNavigateUtils"

import { deleteNote } from "./api"
import type { Note } from "./types"

interface NoteCardProps {
  note: Note
  onEdit: () => void
  onDeleted: () => void
}

export function NoteCard({ note, onEdit, onDeleted }: NoteCardProps) {
  const [confirming, setConfirming] = useState(false)
  const qc = useQueryClient()
  const navigate = useNavigate()

  const deleteMut = useMutation({
    mutationFn: () => deleteNote(note.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["notes-groups"] })
      onDeleted()
    },
  })

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3">
      {/* Header row */}
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {note.document_id && <FileText size={12} />}
        <span className="flex-1 truncate">{relativeDate(note.updated_at)}</span>
        {note.group_name && (
          <span className="rounded-full bg-muted px-2 py-0.5">{note.group_name}</span>
        )}
        <button
          onClick={() => {
            onEdit()
            setConfirming(false)
          }}
          className="hover:text-foreground"
          title="Edit"
        >
          <Pencil size={12} />
        </button>
        <button
          onClick={() => setConfirming((v) => !v)}
          className="hover:text-destructive"
          title="Delete"
        >
          <Trash2 size={12} />
        </button>
      </div>

      {/* Inline delete confirmation */}
      {confirming && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>Delete this note?</span>
          <button
            onClick={() => deleteMut.mutate()}
            disabled={deleteMut.isPending}
            className="rounded bg-destructive px-2 py-0.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
          >
            Yes
          </button>
          <button
            onClick={() => setConfirming(false)}
            className="rounded border border-border px-2 py-0.5 text-xs hover:bg-accent"
          >
            No
          </button>
        </div>
      )}

      {/* Content -- click to open editor dialog */}
      {!confirming && (
        <div className="cursor-pointer" onClick={onEdit}>
          <MarkdownRenderer>{note.content.slice(0, 200)}</MarkdownRenderer>
        </div>
      )}

      {/* Source back-link -- deep-links to the document section this note was created from */}
      {note.document_id && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            const params = new URLSearchParams({ doc: note.document_id! })
            if (note.chunk_id) params.set("chunk_id", note.chunk_id)
            navigate(`/?${params.toString()}`)
          }}
          className="flex items-center gap-1.5 self-start rounded-md border border-border/60 bg-muted/50 px-2.5 py-1 text-xs text-primary hover:bg-accent hover:text-foreground transition-colors"
          title="Open source document"
        >
          <BookOpen size={11} />
          Go to source
        </button>
      )}

      {/* Tags -- breadcrumb style: root in text-primary, /child in text-muted-foreground */}
      {note.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {note.tags.map((t) => {
            const parts = t.split("/")
            return (
              <button
                key={t}
                onClick={(e) => {
                  e.stopPropagation()
                  dispatchTagNavigate(t)
                }}
                className="flex items-center gap-0.5 rounded-full bg-muted px-2 py-0.5 text-xs hover:bg-accent transition-colors"
                title={`Filter by tag: ${t}`}
              >
                <Tag size={9} className="text-muted-foreground" />
                <span className="text-primary">{parts[0]}</span>
                {parts.length > 1 && (
                  <span className="text-muted-foreground">
                    {"/" + parts.slice(1).join("/")}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
