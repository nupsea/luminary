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
 * Collections section (S164):
 *   - Scrollable checkbox list of all collections (GET /collections/tree, flattened)
 *   - Pre-checked based on note's collection_ids
 *   - Check: POST /collections/{id}/notes immediately (no Save required)
 *   - Uncheck: DELETE /collections/{id}/notes/{note_id} immediately
 *
 * After save:
 *   - isFetchingTags=true shows 'Suggesting tags...' with Loader2
 *   - If suggest-tags returns novel tags: dashed-border chips shown
 *   - If suggest-tags returns []: 'No suggestions available' shown briefly (2s)
 *   - Dialog NEVER auto-closes -- user always closes via Done or Cancel
 *   - AbortController cancels in-flight fetch when dialog closes
 */

import { useEffect, useRef, useState } from "react"
import { Loader2, Tag } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { TagAutocomplete } from "@/components/TagAutocomplete"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"

import { API_BASE } from "@/lib/config"
import { flattenCollectionTree } from "@/lib/collectionUtils"
import type { CollectionTreeItem } from "@/lib/collectionUtils"

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
  collection_ids: string[]
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

async function fetchCollectionTree(): Promise<CollectionTreeItem[]> {
  const res = await fetch(`${API_BASE}/collections/tree`)
  if (!res.ok) return []
  return res.json() as Promise<CollectionTreeItem[]>
}

async function addNoteToCollection(collectionId: string, noteId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/collections/${collectionId}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note_ids: [noteId] }),
  })
  if (!res.ok) throw new Error(`POST /collections/${collectionId}/notes failed`)
}

async function removeNoteFromCollection(collectionId: string, noteId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/collections/${collectionId}/notes/${noteId}`, {
    method: "DELETE",
  })
  if (!res.ok && res.status !== 204)
    throw new Error(`DELETE /collections/${collectionId}/notes/${noteId} failed`)
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
  const [isSaved, setIsSaved] = useState(false)
  const [suggestedTags, setSuggestedTags] = useState<string[]>([])
  const [isFetchingTags, setIsFetchingTags] = useState(false)
  const [noSuggestionsMsg, setNoSuggestionsMsg] = useState(false)
  const [savedNote, setSavedNote] = useState<Note | null>(null)
  // Collection IDs that this note belongs to (tracked locally for immediate UI updates).
  const [checkedCollectionIds, setCheckedCollectionIds] = useState<Set<string>>(
    new Set(note?.collection_ids ?? []),
  )
  const qc = useQueryClient()
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Collections list
  const { data: collectionTree, isLoading: collectionsLoading } = useQuery({
    queryKey: ["collections-tree"],
    queryFn: fetchCollectionTree,
    staleTime: 30_000,
    enabled: note !== null,
  })
  const allCollections = collectionTree ? flattenCollectionTree(collectionTree) : []

  // Re-initialise state when note changes (new note selected)
  useEffect(() => {
    if (note) {
      setContent(note.content)
      setEditTags(note.tags ?? [])
      setIsSaved(false)
      setSuggestedTags([])
      setSavedNote(null)
      setIsFetchingTags(false)
      setNoSuggestionsMsg(false)
      setCheckedCollectionIds(new Set(note.collection_ids ?? []))
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
        const normalize = (s: string) => s.toLowerCase().replace(/[-_\s]+/g, "")
        const existingNorm = updated.tags.map(normalize)
        const novel = suggestions.filter((t) => !existingNorm.includes(normalize(t)))
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

  // Immediately fire collection membership changes (no Save required).
  const collectionToggleMut = useMutation({
    mutationFn: ({ collectionId, add }: { collectionId: string; add: boolean }) =>
      add
        ? addNoteToCollection(collectionId, note!.id)
        : removeNoteFromCollection(collectionId, note!.id),
    onSuccess: (_data, { collectionId, add }) => {
      setCheckedCollectionIds((prev) => {
        const next = new Set(prev)
        if (add) next.add(collectionId)
        else next.delete(collectionId)
        return next
      })
      void qc.invalidateQueries({ queryKey: ["collections-tree"] })
      void qc.invalidateQueries({ queryKey: ["notes"] })
    },
  })

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
              <TagAutocomplete
                tags={editTags}
                onChange={(newTags) => {
                  setEditTags(newTags)
                }}
                onUnsavedChange={() => setIsSaved(false)}
              />
            </div>

            {/* Collections section */}
            <div className="shrink-0 border-t border-border px-4 py-2">
              <p className="mb-1 text-xs font-medium text-muted-foreground">Collections</p>
              {collectionsLoading ? (
                <div className="flex flex-col gap-1">
                  {Array.from({ length: 2 }).map((_, i) => (
                    <Skeleton key={i} className="h-5 w-full rounded" />
                  ))}
                </div>
              ) : allCollections.length === 0 ? (
                <p className="text-xs text-muted-foreground">No collections yet</p>
              ) : (
                <div className="max-h-40 overflow-y-auto flex flex-col gap-0.5">
                  {allCollections.map((col) => (
                    <label
                      key={col.id}
                      className="flex items-center gap-2 cursor-pointer rounded px-1 py-0.5 text-xs text-foreground hover:bg-accent/50"
                    >
                      <input
                        type="checkbox"
                        checked={checkedCollectionIds.has(col.id)}
                        onChange={(e) => {
                          collectionToggleMut.mutate({
                            collectionId: col.id,
                            add: e.target.checked,
                          })
                        }}
                        className="h-3 w-3 rounded border-border"
                      />
                      <span
                        className="h-2 w-2 shrink-0 rounded-sm"
                        style={{ backgroundColor: col.color }}
                      />
                      <span className="flex-1 truncate">{col.name}</span>
                    </label>
                  ))}
                </div>
              )}
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
