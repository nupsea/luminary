/**
 * NoteCreationDialog -- lightweight dialog for creating a new note or appending
 * selected text to an existing note.
 *
 * After saving (POST new or PATCH existing), returns the Note object via onSaved
 * so the parent can open NoteEditorDialog for full editing with tag suggestions,
 * markdown preview, etc.
 */

import { useEffect, useState, useCallback } from "react"
import { Search } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import type { SourceRef } from "./SelectionActionBar"
import { API_BASE } from "@/lib/config"
import type { Note } from "@/components/NoteEditorDialog"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ExistingNote {
  id: string
  content: string
  tags: string[]
  updated_at: string
}

interface NoteCreationDialogProps {
  open: boolean
  selectedText: string
  sourceRef: SourceRef | null
  sectionHeading?: string
  onClose: () => void
  /** Called with the saved Note so parent can open NoteEditorDialog on it */
  onSaved: (note: Note) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildBlockquote(text: string, sourceRef: SourceRef | null, sectionHeading?: string): string {
  const parts = [sourceRef?.documentTitle, sectionHeading].filter(Boolean)
  const attribution = parts.length > 0 ? parts.join(", ") : ""
  return `> "${text}"\n>\n> -- ${attribution}`
}

function formatRelativeDate(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1) return "just now"
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.floor(diffHours / 24)
  if (diffDays < 30) return `${diffDays}d ago`
  return date.toLocaleDateString()
}

function firstLine(content: string): string {
  const line = content.split("\n").find((l) => l.trim().length > 0) ?? ""
  return line.length > 80 ? line.slice(0, 80) + "..." : line
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function NoteCreationDialog({
  open,
  selectedText,
  sourceRef,
  sectionHeading,
  onClose,
  onSaved,
}: NoteCreationDialogProps) {
  type Mode = "new" | "existing"

  const [mode, setMode] = useState<Mode>("new")
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Existing-note selector state
  const [existingNotes, setExistingNotes] = useState<ExistingNote[]>([])
  const [notesLoading, setNotesLoading] = useState(false)
  const [filterText, setFilterText] = useState("")
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null)

  // Reset state when dialog opens
  useEffect(() => {
    if (open) {
      setMode("new")
      setSaveError(null)
      setSelectedNoteId(null)
      setFilterText("")
    }
  }, [open, selectedText])

  // Fetch existing notes for this document when dialog opens
  useEffect(() => {
    if (open && sourceRef?.documentId) {
      setNotesLoading(true)
      fetch(`${API_BASE}/notes?document_id=${sourceRef.documentId}`)
        .then((res) => (res.ok ? (res.json() as Promise<ExistingNote[]>) : Promise.resolve([])))
        .then((notes) => setExistingNotes(notes))
        .catch(() => setExistingNotes([]))
        .finally(() => setNotesLoading(false))
    }
  }, [open, sourceRef?.documentId])

  const switchToNew = useCallback(() => {
    setMode("new")
    setSelectedNoteId(null)
  }, [])

  const switchToExisting = useCallback(() => {
    setMode("existing")
    setSelectedNoteId(null)
  }, [])

  async function handleSave() {
    if (!sourceRef) return
    setSaving(true)
    setSaveError(null)

    const blockquote = buildBlockquote(selectedText, sourceRef, sectionHeading)

    try {
      let result: Note
      if (mode === "existing" && selectedNoteId) {
        // Find the selected note and append the passage
        const existing = existingNotes.find((n) => n.id === selectedNoteId)
        if (!existing) throw new Error("Selected note not found")
        const mergedContent = existing.content + "\n\n---\n\n" + blockquote
        const res = await fetch(`${API_BASE}/notes/${selectedNoteId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: mergedContent }),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        result = (await res.json()) as Note
      } else {
        // POST new note
        const res = await fetch(`${API_BASE}/notes`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            document_id: sourceRef.documentId,
            section_id: sourceRef.sectionId ?? null,
            content: blockquote,
            tags: [],
            group_name: null,
          }),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        result = (await res.json()) as Note
      }
      onSaved(result)
      onClose()
    } catch {
      setSaveError("Failed to save note. Please try again.")
    } finally {
      setSaving(false)
    }
  }

  const filteredNotes = existingNotes.filter((n) => {
    if (!filterText.trim()) return true
    const lower = filterText.toLowerCase()
    return (
      n.content.toLowerCase().includes(lower) ||
      n.tags.some((t) => t.toLowerCase().includes(lower))
    )
  })

  const canSave = mode === "new" || selectedNoteId !== null

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Add to Note</DialogTitle>
          <DialogDescription className="sr-only">
            Create a new note or append to an existing note
          </DialogDescription>
        </DialogHeader>

        {/* Selected passage (read-only) */}
        <div className="rounded-md bg-muted/30 px-4 py-3">
          <p className="mb-1 text-xs font-medium text-muted-foreground">Selected passage</p>
          <blockquote className="border-l-2 border-primary/40 pl-3 text-sm italic text-foreground/80">
            &ldquo;{selectedText.length > 300 ? selectedText.slice(0, 300) + "..." : selectedText}&rdquo;
            {(sourceRef?.documentTitle || sectionHeading) && (
              <span className="mt-1 block text-xs not-italic text-muted-foreground">
                -- {[sourceRef?.documentTitle, sectionHeading].filter(Boolean).join(", ")}
              </span>
            )}
          </blockquote>
        </div>

        {/* Target selector */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={switchToNew}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              mode === "new"
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground"
            }`}
          >
            New note
          </button>
          <button
            type="button"
            onClick={switchToExisting}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              mode === "existing"
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground"
            }`}
          >
            Add to existing
          </button>
        </div>

        {/* Existing note selector */}
        {mode === "existing" && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Search size={13} className="text-muted-foreground" />
              <input
                type="text"
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                placeholder="Filter notes..."
                className="flex-1 bg-transparent text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
              />
            </div>
            <div className="max-h-40 overflow-auto space-y-1">
              {notesLoading && (
                <p className="text-xs text-muted-foreground py-2">Loading notes...</p>
              )}
              {!notesLoading && filteredNotes.length === 0 && (
                <p className="text-xs text-muted-foreground py-2">No notes found for this document.</p>
              )}
              {filteredNotes.map((note) => (
                <button
                  key={note.id}
                  type="button"
                  onClick={() => setSelectedNoteId(note.id)}
                  className={`w-full text-left rounded-md border px-3 py-2 transition-colors ${
                    selectedNoteId === note.id
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-muted-foreground/30 hover:bg-muted/50"
                  }`}
                >
                  <p className="text-xs text-foreground truncate">{firstLine(note.content)}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-[10px] text-muted-foreground">
                      {formatRelativeDate(note.updated_at)}
                    </span>
                    {note.tags.slice(0, 3).map((t) => (
                      <span
                        key={t}
                        className="rounded-full bg-muted px-1.5 py-0 text-[10px] text-muted-foreground"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* New note info */}
        {mode === "new" && (
          <p className="text-xs text-muted-foreground">
            A new note will be created with the selected passage as a blockquote. You can edit it in the full editor after saving.
          </p>
        )}

        {saveError && (
          <p className="text-xs text-destructive">{saveError}</p>
        )}

        <DialogFooter>
          <button
            onClick={onClose}
            className="rounded border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
          >
            Cancel
          </button>
          <button
            onClick={() => void handleSave()}
            disabled={saving || !canSave}
            className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? "Saving..." : mode === "existing" ? "Append & Edit" : "Create & Edit"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
