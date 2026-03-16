/**
 * NoteEditorDialog -- focused Write + Preview dialog for note editing.
 *
 * Opens when `note` prop is non-null. Two-column layout:
 *   Left:  full-height monospace textarea (Write pane)
 *   Right: real-time MarkdownRenderer (Preview pane)
 *
 * Keyboard shortcut: Ctrl+S / Cmd+S triggers Save (only when not yet saved).
 * Tags section is editable: chips with X to remove, inline input to add.
 *
 * After save:
 *   - isFetchingTags=true shows 'Suggesting tags...' with Loader2
 *   - If suggest-tags returns novel tags: dashed-border chips shown
 *   - If suggest-tags returns []: 'No suggestions available' shown briefly (2s)
 *   - Dialog NEVER auto-closes -- user always closes via Done or Cancel
 *   - AbortController cancels in-flight fetch when dialog closes
 */

import { useEffect, useRef, useState } from "react"
import { Loader2, Tag, X } from "lucide-react"
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

import { API_BASE } from "@/lib/config"

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

async function fetchSuggestedTags(id: string, signal?: AbortSignal): Promise<string[]> {
  try {
    const res = await fetch(`${API_BASE}/notes/${id}/suggest-tags`, {
      method: "POST",
      signal,
    })
    if (!res.ok) return []
    const data = (await res.json()) as { tags: string[] }
    return data.tags ?? []
  } catch {
    return []
  }
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
  const [editTags, setEditTags] = useState<string[]>(note?.tags ?? [])
  const [tagInput, setTagInput] = useState("")
  const [isSaved, setIsSaved] = useState(false)
  const [suggestedTags, setSuggestedTags] = useState<string[]>([])
  const [isFetchingTags, setIsFetchingTags] = useState(false)
  const [noSuggestionsMsg, setNoSuggestionsMsg] = useState(false)
  const [savedNote, setSavedNote] = useState<Note | null>(null)
  const qc = useQueryClient()
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Re-initialise state when note changes (new note selected)
  useEffect(() => {
    if (note) {
      setContent(note.content)
      setEditTags(note.tags ?? [])
      setTagInput("")
      setIsSaved(false)
      setSuggestedTags([])
      setSavedNote(null)
      setIsFetchingTags(false)
      setNoSuggestionsMsg(false)
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

  function handleClose() {
    abortRef.current?.abort()
    onClose()
  }

  const saveMut = useMutation({
    mutationFn: () => patchNote(note!.id, { content, tags: editTags }),
    onSuccess: (updated) => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      setSavedNote(updated)
      setIsSaved(true)

      // Fire suggest-tags with AbortController; abort any in-flight fetch first
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      setIsFetchingTags(true)

      void fetchSuggestedTags(updated.id, controller.signal).then((suggestions) => {
        if (controller.signal.aborted) return
        setIsFetchingTags(false)
        const novel = suggestions.filter((t) => !updated.tags.includes(t))
        if (novel.length > 0) {
          setSuggestedTags(novel)
        } else {
          setNoSuggestionsMsg(true)
          setTimeout(() => setNoSuggestionsMsg(false), 2000)
        }
      })
    },
  })

  const addTagMut = useMutation({
    mutationFn: (tag: string) => {
      const current = savedNote?.tags ?? note!.tags
      return patchNote(note!.id, { tags: [...current, tag] })
    },
    onSuccess: (updated) => {
      setSavedNote(updated)
      setEditTags(updated.tags)
      void qc.invalidateQueries({ queryKey: ["notes"] })
      setSuggestedTags((prev) => prev.filter((t) => !updated.tags.includes(t)))
    },
  })

  function commitTagInput() {
    const trimmed = tagInput.trim().replace(/,+$/, "").trim()
    if (trimmed && !editTags.includes(trimmed)) {
      setEditTags((prev) => [...prev, trimmed])
      setIsSaved(false)
    }
    setTagInput("")
  }

  const isOpen = note !== null
  const unchanged =
    content === (note?.content ?? "") &&
    JSON.stringify([...editTags].sort()) === JSON.stringify([...(note?.tags ?? [])].sort())

  // Ctrl+S / Cmd+S shortcut -- only active when isSaved=false
  useEffect(() => {
    if (!note) return
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault()
        if (!isSaved && !saveMut.isPending && !unchanged) {
          saveMut.mutate()
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [note, saveMut, isSaved, unchanged])

  function handleDone() {
    onSaved(savedNote ?? note!)
    handleClose()
  }

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) handleClose() }}>
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
              onChange={(e) => {
                setContent(e.target.value)
                setIsSaved(false)
              }}
              className="flex-1 resize-none bg-background px-4 py-3 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
              placeholder="Write your note in Markdown..."
            />
            {/* Editable tags section below write pane */}
            <div className="shrink-0 border-t border-border px-4 py-2">
              <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
                {note?.group_name && (
                  <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    {note.group_name}
                  </span>
                )}
                {editTags.map((t) => (
                  <span
                    key={t}
                    className="flex items-center gap-0.5 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                  >
                    <Tag size={9} />
                    {t}
                    <button
                      type="button"
                      onClick={() => {
                        setEditTags((prev) => prev.filter((x) => x !== t))
                        setIsSaved(false)
                      }}
                      className="ml-0.5 hover:text-foreground"
                      aria-label={`Remove tag ${t}`}
                    >
                      <X size={9} />
                    </button>
                  </span>
                ))}
              </div>
              <input
                type="text"
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === ",") {
                    e.preventDefault()
                    commitTagInput()
                  }
                }}
                placeholder="Add tag..."
                className="w-full bg-transparent text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
              />
            </div>
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
        <DialogFooter className="shrink-0 flex-col items-stretch gap-2 border-t border-border px-6 py-3">
          {/* Tag suggestion area -- shown after save */}
          {isSaved && (
            <>
              {isFetchingTags && (
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 size={11} className="animate-spin" />
                  <span>Suggesting tags...</span>
                </div>
              )}
              {!isFetchingTags && noSuggestionsMsg && (
                <p className="text-xs text-muted-foreground">No suggestions available</p>
              )}
              {!isFetchingTags && suggestedTags.length > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-muted-foreground">Suggested tags:</span>
                  {suggestedTags.map((tag) => (
                    <button
                      key={tag}
                      onClick={() => addTagMut.mutate(tag)}
                      disabled={addTagMut.isPending}
                      className="flex items-center gap-0.5 rounded-full border border-dashed border-border bg-muted px-2 py-0.5 text-xs text-foreground hover:bg-accent disabled:opacity-50"
                    >
                      <Tag size={9} />
                      {tag}
                    </button>
                  ))}
                  <button
                    onClick={() => setSuggestedTags([])}
                    className="text-xs text-muted-foreground underline hover:text-foreground"
                  >
                    Dismiss
                  </button>
                </div>
              )}
            </>
          )}

          {/* Action row */}
          <div className="flex flex-row items-center justify-between">
            <div className="flex-1">
              {saveMut.isError && (
                <p className="text-xs text-red-600">Failed to save. Please try again.</p>
              )}
            </div>
            <div className="flex items-center gap-2">
              {isSaved ? (
                <button
                  onClick={handleDone}
                  className="rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
                >
                  Done
                </button>
              ) : (
                <>
                  <button
                    onClick={handleClose}
                    className="rounded border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => saveMut.mutate()}
                    disabled={unchanged || saveMut.isPending}
                    className="flex items-center gap-1.5 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {saveMut.isPending && <Loader2 size={11} className="animate-spin" />}
                    Save
                  </button>
                </>
              )}
            </div>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
