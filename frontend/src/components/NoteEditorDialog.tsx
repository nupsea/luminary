/**
 * NoteEditorDialog — focused Write + Preview dialog for note editing.
 *
 * Opens when `note` prop is non-null. Two-column layout:
 *   Left:  full-height monospace textarea (Write pane)
 *   Right: real-time MarkdownRenderer (Preview pane)
 *
 * Keyboard shortcut: Ctrl+S / Cmd+S triggers Save.
 * Tags and group_name displayed read-only below the Write pane.
 */

import { useEffect, useRef, useState } from "react"
import { Loader2, Tag } from "lucide-react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

const API_BASE = "http://localhost:8000"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Note {
  id: string
  document_id: string | null
  chunk_id: string | null
  content: string
  tags: string[]
  group_name: string | null
  created_at: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function patchNote(
  id: string,
  data: { content?: string; tags?: string[]; group_name?: string },
): Promise<Note> {
  const res = await fetch(`${API_BASE}/notes/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`PATCH /notes/${id} failed: ${res.status}`)
  return res.json() as Promise<Note>
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface NoteEditorDialogProps {
  note: Note | null
  onClose: () => void
  onSaved: (updated: Note) => void
}

export function NoteEditorDialog({ note, onClose, onSaved }: NoteEditorDialogProps) {
  const [content, setContent] = useState(note?.content ?? "")
  const qc = useQueryClient()
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Re-initialise content when note changes (new note selected)
  useEffect(() => {
    if (note) {
      setContent(note.content)
      saveMut.reset()
    }
    // saveMut.reset is stable; note drives initialisation
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [note?.id])

  // Focus textarea when dialog opens
  useEffect(() => {
    if (note && textareaRef.current) {
      textareaRef.current.focus()
    }
  }, [note])

  const saveMut = useMutation({
    mutationFn: (newContent: string) => patchNote(note!.id, { content: newContent }),
    onSuccess: (updated) => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      onSaved(updated)
      onClose()
    },
  })

  // Ctrl+S / Cmd+S shortcut
  useEffect(() => {
    if (!note) return
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault()
        if (!saveMut.isPending && content !== note!.content) {
          saveMut.mutate(content)
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [note, content, saveMut])

  const isOpen = note !== null
  const unchanged = content === (note?.content ?? "")

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="flex h-[80vh] w-[90vw] max-w-5xl flex-col rounded-lg border border-border p-0 gap-0">
        <DialogHeader className="shrink-0 border-b border-border px-6 py-4">
          <DialogTitle className="text-base font-semibold text-foreground">
            Edit Note
          </DialogTitle>
          <DialogDescription className="sr-only">Note editor</DialogDescription>
        </DialogHeader>

        {/* Two-column editor area */}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {/* Write pane */}
          <div className="flex w-1/2 flex-col border-r border-border">
            <div className="shrink-0 border-b border-border px-4 py-2">
              <span className="text-xs font-medium text-muted-foreground">Write</span>
            </div>
            <textarea
              ref={textareaRef}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="flex-1 resize-none bg-background px-4 py-3 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
              placeholder="Write your note in Markdown..."
            />
            {/* Read-only tags and group below write pane */}
            {note && (note.tags.length > 0 || note.group_name) && (
              <div className="shrink-0 flex flex-wrap items-center gap-2 border-t border-border px-4 py-2">
                {note.group_name && (
                  <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    {note.group_name}
                  </span>
                )}
                {note.tags.map((t) => (
                  <span
                    key={t}
                    className="flex items-center gap-0.5 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                  >
                    <Tag size={9} />
                    {t}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Preview pane */}
          <div className="flex w-1/2 flex-col">
            <div className="shrink-0 border-b border-border px-4 py-2">
              <span className="text-xs font-medium text-muted-foreground">Preview</span>
            </div>
            <div className="flex-1 overflow-auto px-4 py-3 text-sm">
              {content ? (
                <MarkdownRenderer>{content}</MarkdownRenderer>
              ) : (
                <p className="text-muted-foreground">Nothing to preview yet.</p>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <DialogFooter className="shrink-0 flex-row items-center justify-between border-t border-border px-6 py-3">
          <div className="flex-1">
            {saveMut.isError && (
              <p className="text-xs text-red-600">Failed to save. Please try again.</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="rounded border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
            <button
              onClick={() => saveMut.mutate(content)}
              disabled={unchanged || saveMut.isPending}
              className="flex items-center gap-1.5 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saveMut.isPending && <Loader2 size={11} className="animate-spin" />}
              Save
            </button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
