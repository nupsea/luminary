/**
 * NoteReaderSheet -- full-width reader/editor panel for notes.
 *
 * Replaces NoteEditorDialog as the primary note-viewing surface in Notes.tsx.
 * Opens as a Sheet from the right occupying 75% of the viewport width.
 *
 * Read mode: full MarkdownRenderer for note content, clickable tag chips,
 * optional source-document subtitle link, floating action bar (Edit, Delete).
 *
 * Edit mode: textarea replaces content, expandable tag/collection sections
 * below the content, floating bar swaps to Save/Cancel.
 *
 * Tag chips dispatch luminary:navigate { tab:'notes', filter:{ tag } } so
 * clicking a tag filters the note list to that tag (handled in App.tsx).
 */

import { useEffect, useRef, useState } from "react"
import { Pencil, Tag, Trash2 } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { TagAutocomplete } from "@/components/TagAutocomplete"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { API_BASE } from "@/lib/config"
import { flattenCollectionTree } from "@/lib/collectionUtils"
import type { CollectionTreeItem } from "@/lib/collectionUtils"
import { stripMarkdown } from "@/lib/utils"
import { dispatchTagNavigate } from "@/lib/noteNavigateUtils"

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
  source_document_ids: string[]
  created_at: string
  updated_at: string
}

interface DocumentItem {
  id: string
  title: string
}

export interface NoteReaderSheetProps {
  note: Note | null
  documents: DocumentItem[]
  onClose: () => void
  onSaved: () => void
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function patchNote(
  id: string,
  data: { content?: string; tags?: string[] },
): Promise<Note> {
  const res = await fetch(`${API_BASE}/notes/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`PATCH /notes/${id} failed: ${res.status}`)
  return res.json() as Promise<Note>
}

async function deleteNote(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/notes/${id}`, { method: "DELETE" })
  if (!res.ok && res.status !== 204)
    throw new Error(`DELETE /notes/${id} failed: ${res.status}`)
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

export function NoteReaderSheet({ note, documents, onClose, onSaved }: NoteReaderSheetProps) {
  const [mode, setMode] = useState<"read" | "edit">("read")
  const [editContent, setEditContent] = useState("")
  const [editTags, setEditTags] = useState<string[]>([])
  const [checkedCollectionIds, setCheckedCollectionIds] = useState<Set<string>>(new Set())
  const [confirmDelete, setConfirmDelete] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const qc = useQueryClient()

  // Re-initialise local state when note changes
  useEffect(() => {
    if (note) {
      setEditContent(note.content)
      setEditTags(note.tags ?? [])
      setCheckedCollectionIds(new Set(note.collection_ids ?? []))
      setMode("read")
      setConfirmDelete(false)
    }
  }, [note?.id])

  // Focus textarea when entering edit mode
  useEffect(() => {
    if (mode === "edit" && textareaRef.current) {
      textareaRef.current.focus()
    }
  }, [mode])

  // Ctrl+S / Cmd+S saves in edit mode
  useEffect(() => {
    if (mode !== "edit") return
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault()
        saveMut.mutate()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
    // saveMut intentionally omitted -- effect re-runs on mode change only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode])

  // Collections list (only needed in edit mode)
  const { data: collectionTree, isLoading: collectionsLoading } = useQuery({
    queryKey: ["collections-tree"],
    queryFn: fetchCollectionTree,
    staleTime: 30_000,
    enabled: note !== null && mode === "edit",
  })
  const allCollections = collectionTree ? flattenCollectionTree(collectionTree) : []

  const saveMut = useMutation({
    mutationFn: () => patchNote(note!.id, { content: editContent, tags: editTags }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      setMode("read")
      onSaved()
    },
  })

  const deleteMut = useMutation({
    mutationFn: () => deleteNote(note!.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["notes-groups"] })
      onClose()
    },
  })

  function handleCollectionToggle(collectionId: string, checked: boolean) {
    if (!note) return
    if (checked) {
      void addNoteToCollection(collectionId, note.id).then(() => {
        setCheckedCollectionIds((prev) => new Set([...prev, collectionId]))
        void qc.invalidateQueries({ queryKey: ["notes"] })
      })
    } else {
      void removeNoteFromCollection(collectionId, note.id).then(() => {
        setCheckedCollectionIds((prev) => {
          const next = new Set(prev)
          next.delete(collectionId)
          return next
        })
        void qc.invalidateQueries({ queryKey: ["notes"] })
      })
    }
  }

  function handleCancelEdit() {
    setMode("read")
    setEditContent(note?.content ?? "")
    setEditTags(note?.tags ?? [])
  }

  // Derive title from first non-empty stripped line
  const title = note
    ? stripMarkdown(note.content).split("\n").find((l) => l.trim()) ?? "Untitled"
    : ""

  // Source document lookup (primary document_id for subtitle)
  const sourceDoc = note?.document_id
    ? (documents.find((d) => d.id === note.document_id) ?? null)
    : null

  return (
    <Sheet open={note !== null} onOpenChange={(open) => { if (!open) onClose() }}>
      <SheetContent
        side="right"
        className="w-[75vw] max-w-4xl sm:max-w-4xl flex flex-col p-0 overflow-hidden"
      >
        {/* Header */}
        <SheetHeader className="px-6 pt-6 pb-4 border-b border-border shrink-0">
          <SheetTitle className="text-xl font-semibold leading-tight pr-8 truncate">
            {title || "Untitled"}
          </SheetTitle>
          {sourceDoc && (
            <SheetDescription asChild>
              <button
                className="w-fit text-left text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
                onClick={() => {
                  window.dispatchEvent(
                    new CustomEvent("luminary:navigate", {
                      detail: { tab: "learning", documentId: sourceDoc.id },
                    }),
                  )
                  onClose()
                }}
              >
                {sourceDoc.title}
              </button>
            </SheetDescription>
          )}
        </SheetHeader>

        {/* Scrollable content area */}
        <div className="flex-1 overflow-auto px-6 py-5 pb-24">
          {mode === "read" ? (
            <>
              {/* Note content */}
              {note === null ? (
                <div className="flex flex-col gap-3">
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-2/3" />
                </div>
              ) : note.content.trim() ? (
                <MarkdownRenderer>{note.content}</MarkdownRenderer>
              ) : (
                <p className="text-muted-foreground italic text-sm">Start writing...</p>
              )}

              {/* Clickable tag chips */}
              {note && note.tags.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-6">
                  {note.tags.map((t) => {
                    const parts = t.split("/")
                    return (
                      <button
                        key={t}
                        onClick={() => dispatchTagNavigate(t)}
                        className="flex items-center gap-1 rounded-full bg-muted px-3 py-1 text-xs hover:bg-accent transition-colors"
                        title={`Filter notes by tag: ${t}`}
                      >
                        <Tag size={10} className="text-muted-foreground" />
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
            </>
          ) : (
            /* Edit mode */
            <>
              <textarea
                ref={textareaRef}
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                placeholder="Write your note in Markdown..."
                className="w-full min-h-[300px] resize-y rounded border border-border bg-background px-3 py-2 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              />

              {/* Tags section (expandable) */}
              <details className="mt-4 rounded border border-border">
                <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-foreground hover:bg-accent/50">
                  Tags
                </summary>
                <div className="px-3 pb-3 pt-1">
                  <TagAutocomplete tags={editTags} onChange={setEditTags} />
                </div>
              </details>

              {/* Collections section (expandable) */}
              <details className="mt-2 rounded border border-border">
                <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-foreground hover:bg-accent/50">
                  Collections
                </summary>
                <div className="px-3 pb-3 pt-1 max-h-48 overflow-y-auto">
                  {collectionsLoading ? (
                    <div className="flex flex-col gap-1">
                      {Array.from({ length: 2 }).map((_, i) => (
                        <Skeleton key={i} className="h-5 w-full rounded" />
                      ))}
                    </div>
                  ) : allCollections.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No collections yet</p>
                  ) : (
                    <div className="flex flex-col gap-0.5">
                      {allCollections.map((col) => (
                        <label
                          key={col.id}
                          className="flex items-center gap-2 cursor-pointer rounded px-1 py-0.5 text-xs text-foreground hover:bg-accent/50"
                        >
                          <input
                            type="checkbox"
                            checked={checkedCollectionIds.has(col.id)}
                            onChange={(e) => handleCollectionToggle(col.id, e.target.checked)}
                            className="h-3 w-3 rounded border-border"
                          />
                          <span
                            className="h-2 w-2 shrink-0 rounded-sm"
                            style={{ backgroundColor: col.color }}
                          />
                          <span>{col.name}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </details>

              {saveMut.isError && (
                <p className="mt-2 text-xs text-red-600">Failed to save. Please try again.</p>
              )}
            </>
          )}
        </div>

        {/* Floating action bar -- absolute over the sheet content */}
        <div className="absolute bottom-6 right-6 flex items-center gap-2">
          {mode === "read" ? (
            confirmDelete ? (
              <>
                <span className="text-xs text-muted-foreground">Delete note?</span>
                <button
                  onClick={() => deleteMut.mutate()}
                  disabled={deleteMut.isPending}
                  className="rounded bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
                >
                  Yes
                </button>
                <button
                  onClick={() => setConfirmDelete(false)}
                  className="rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
                >
                  No
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={() => { setMode("edit"); setConfirmDelete(false) }}
                  className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 shadow-sm"
                  title="Edit note"
                >
                  <Pencil size={12} />
                  Edit
                </button>
                <button
                  onClick={() => setConfirmDelete(true)}
                  className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs text-muted-foreground hover:text-destructive hover:border-destructive shadow-sm"
                  title="Delete note"
                >
                  <Trash2 size={12} />
                </button>
              </>
            )
          ) : (
            <>
              <button
                onClick={() => saveMut.mutate()}
                disabled={saveMut.isPending}
                className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 shadow-sm"
              >
                {saveMut.isPending ? "Saving..." : "Save"}
              </button>
              <button
                onClick={handleCancelEdit}
                className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent shadow-sm"
              >
                Cancel
              </button>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
