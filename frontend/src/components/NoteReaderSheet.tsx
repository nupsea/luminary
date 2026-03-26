/**
 * NoteReaderSheet -- full-width reader/editor panel for notes.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import { Check, FileText, LayoutGrid, Loader2, Pencil, Tag, Trash2, Wand2, X } from "lucide-react"
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
  // S175: multi-document source linkage
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
  onSaved: (note: Note) => void
  isNew?: boolean
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function createNote(payload: {
  content: string
  tags: string[]
  document_id: string | null
  source_document_ids?: string[]
}): Promise<Note> {
  const res = await fetch(`${API_BASE}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`POST /notes failed: ${res.status}`)
  return res.json() as Promise<Note>
}

async function patchNote(
  id: string,
  data: { content?: string; tags?: string[]; source_document_ids?: string[] },
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

export function NoteReaderSheet({
  note,
  documents,
  onClose,
  onSaved,
  isNew = false,
}: NoteReaderSheetProps) {
  const [mode, setMode] = useState<"read" | "edit">(isNew ? "edit" : "read")
  const [editContent, setEditContent] = useState("")
  const [editTags, setEditTags] = useState<string[]>([])
  const [checkedCollectionIds, setCheckedCollectionIds] = useState<Set<string>>(new Set())
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [suggestedTags, setSuggestedTags] = useState<string[]>([])
  const [isFetchingTags, setIsFetchingTags] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const qc = useQueryClient()

  const adjustHeight = useCallback(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = "auto"
    ta.style.height = `${ta.scrollHeight}px`
  }, [])

  // Re-initialise local state when note changes or isNew changes
  useEffect(() => {
    if (isNew) {
      setEditContent("")
      setEditTags([])
      setCheckedCollectionIds(new Set())
      setSelectedDocIds([])
      setMode("edit")
      setConfirmDelete(false)
      setSuggestedTags([])
      setIsFetchingTags(false)
    } else if (note) {
      setEditContent(note.content)
      setEditTags(note.tags ?? [])
      setCheckedCollectionIds(new Set(note.collection_ids ?? []))
      setSelectedDocIds(
        note.source_document_ids?.length > 0
          ? note.source_document_ids
          : note.document_id
            ? [note.document_id]
            : [],
      )
      setMode("read")
      setConfirmDelete(false)
      setSuggestedTags([])
      setIsFetchingTags(false)
    }
  }, [note?.id, isNew])

  // Focus textarea when entering edit mode
  useEffect(() => {
    if (mode === "edit" && textareaRef.current) {
      textareaRef.current.focus()
      adjustHeight()

      // Auto-trigger tag suggestions if note has no tags
      if (!isNew && note && note.tags.length === 0 && editContent.trim().length > 20) {
        void handleFetchSuggestions(true)
      }
    }
  }, [mode, adjustHeight, isNew, editContent, note])

  async function handleFetchSuggestions(autoAdd = false) {
    if (!note && !isNew) return
    // Tag suggestions for brand new notes aren't supported yet 
    if (!note) return 

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setIsFetchingTags(true)
    try {
      const suggestions = await fetchSuggestedTags(note.id, controller.signal)
      if (controller.signal.aborted) return

      if (autoAdd && editTags.length === 0) {
        setEditTags(suggestions)
        setSuggestedTags([])
      } else {
        const novel = suggestions.filter((t) => !editTags.includes(t))
        setSuggestedTags(novel)
      }
    } finally {
      if (!controller.signal.aborted) setIsFetchingTags(false)
    }
  }

  function handleAddSuggestedTag(tag: string) {
    setEditTags((prev) => [...new Set([...prev, tag])])
    setSuggestedTags((prev) => prev.filter((t) => t !== tag))
  }

  // Adjust height on content change
  useEffect(() => {
    if (mode === "edit") {
      adjustHeight()
    }
  }, [editContent, mode, adjustHeight])

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
  }, [mode])

  // Collections list
  const { data: collectionTree, isLoading: collectionsLoading } = useQuery({
    queryKey: ["collections-tree"],
    queryFn: fetchCollectionTree,
    staleTime: 30_000,
    enabled: note !== null || isNew,
  })
  const allCollections = collectionTree ? flattenCollectionTree(collectionTree) : []

  const saveMut = useMutation({
    mutationFn: async () => {
      if (isNew) {
        return createNote({
          content: editContent,
          tags: editTags,
          document_id: selectedDocIds[0] || null,
          source_document_ids: selectedDocIds,
        })
      } else {
        return patchNote(note!.id, {
          content: editContent,
          tags: editTags,
          source_document_ids: selectedDocIds,
        })
      }
    },
    onSuccess: (savedNote) => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      if (!isNew) {
        setMode("read")
      }
      onSaved(savedNote)
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
    if (isNew) {
      onClose()
      return
    }
    setMode("read")
    setEditContent(note?.content ?? "")
    setEditTags(note?.tags ?? [])
    setSelectedDocIds(note?.source_document_ids ?? (note?.document_id ? [note.document_id] : []))
  }

  const title = isNew
    ? "New Note"
    : note
      ? stripMarkdown(note.content).split("\n").find((l) => l.trim()) ?? "Untitled"
      : ""

  const sourceDoc = !isNew && note?.document_id
    ? (documents.find((d) => d.id === note.document_id) ?? null)
    : null

  return (
    <Sheet open={note !== null || isNew} onOpenChange={(open) => { if (!open) onClose() }}>
      <SheetContent
        side="right"
        className="w-[85vw] max-w-5xl sm:max-w-6xl flex flex-col p-0 overflow-hidden"
      >
        <SheetHeader className="px-6 pt-6 pb-4 border-b border-border shrink-0">
          <SheetTitle className="text-xl font-semibold leading-tight pr-8 truncate">
            {title}
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

        <div className="flex-1 overflow-auto">
          <div className="px-6 py-5 min-h-full flex flex-col">
            {mode === "read" && !isNew ? (
              <div
                className="flex-1 cursor-text select-text"
                onDoubleClick={() => setMode("edit")}
                title="Double-click to edit"
              >
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
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-8 items-start flex-1">
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Editor</span>
                  </div>
                  <textarea
                    ref={textareaRef}
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    placeholder="Write your note in Markdown..."
                    className="w-full resize-none overflow-hidden rounded border-none bg-background py-1 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-0"
                  />
                </div>
                <div className="flex flex-col gap-2 border-l border-border pl-8 min-h-full">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Preview</span>
                  </div>
                  <div className="prose-sm">
                    {editContent.trim() ? (
                      <MarkdownRenderer>{editContent}</MarkdownRenderer>
                    ) : (
                      <p className="text-muted-foreground italic text-sm">Preview will appear here...</p>
                    )}
                  </div>
                </div>
              </div>
            )}

            <div className="mt-12 pt-8 border-t border-border space-y-6 pb-24">
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Tag size={12} />
                    <span className="text-[10px] font-bold uppercase tracking-wider">Tags</span>
                  </div>
                  {mode === "edit" && !isNew && (
                    <button
                      onClick={() => void handleFetchSuggestions()}
                      disabled={isFetchingTags}
                      className="flex items-center gap-1 text-[10px] text-primary hover:underline disabled:opacity-50"
                    >
                      {isFetchingTags ? (
                        <Loader2 size={10} className="animate-spin" />
                      ) : (
                        <Wand2 size={10} />
                      )}
                      Suggest tags
                    </button>
                  )}
                </div>
                {mode === "read" && !isNew ? (
                  <div className="flex flex-wrap gap-1.5">
                    {note?.tags.length ? (
                      note.tags.map((t) => {
                        const parts = t.split("/")
                        return (
                          <button
                            key={t}
                            onClick={() => dispatchTagNavigate(t)}
                            className="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs hover:bg-accent transition-colors"
                          >
                            <span className="text-primary">{parts[0]}</span>
                            {parts.length > 1 && (
                              <span className="text-muted-foreground">{"/" + parts.slice(1).join("/")}</span>
                            )}
                          </button>
                        )
                      })
                    ) : (
                      <span className="text-xs text-muted-foreground italic">No tags</span>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-col gap-3">
                    <TagAutocomplete tags={editTags} onChange={setEditTags} />
                    {!isNew && suggestedTags.length > 0 && (
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[10px] font-medium text-muted-foreground">Suggestions:</span>
                        {suggestedTags.map((tag) => (
                          <button
                            key={tag}
                            onClick={() => handleAddSuggestedTag(tag)}
                            className="flex items-center gap-1 rounded-full border border-dashed border-primary/30 bg-primary/5 px-2 py-0.5 text-[11px] text-primary hover:bg-primary/10 transition-colors"
                          >
                            <Check size={9} />
                            {tag}
                          </button>
                        ))}
                        <button
                          onClick={() => setSuggestedTags([])}
                          className="text-[10px] text-muted-foreground hover:underline"
                        >
                          Dismiss
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <LayoutGrid size={12} />
                    <span className="text-[10px] font-bold uppercase tracking-wider">Collections</span>
                  </div>
                  {mode === "read" && !isNew ? (
                    <div className="flex flex-wrap gap-1.5">
                      {note && note.collection_ids.length > 0 ? (
                        allCollections
                          .filter((c) => checkedCollectionIds.has(c.id))
                          .map((c) => (
                            <div key={c.id} className="flex items-center gap-1.5 rounded bg-muted px-2 py-0.5 text-xs">
                              <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: c.color }} />
                              {c.name}
                            </div>
                          ))
                      ) : (
                        <span className="text-xs text-muted-foreground italic">Standalone note</span>
                      )}
                    </div>
                  ) : (
                    <div className="max-h-40 overflow-y-auto flex flex-col gap-1">
                      {collectionsLoading ? (
                        <Skeleton className="h-4 w-24" />
                      ) : (
                        allCollections.map((col) => (
                          <label
                            key={col.id}
                            className={`flex items-center gap-2 cursor-pointer rounded px-1 py-0.5 text-xs text-foreground hover:bg-accent/50 ${isNew ? 'opacity-50 cursor-not-allowed' : ''}`}
                            title={isNew ? "Create the note first to add to collections" : ""}
                          >
                            <input
                              type="checkbox"
                              checked={checkedCollectionIds.has(col.id)}
                              onChange={(e) => handleCollectionToggle(col.id, e.target.checked)}
                              disabled={isNew}
                              className="h-3 w-3 rounded border-border"
                            />
                            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: col.color }} />
                            <span className="truncate">{col.name}</span>
                          </label>
                        ))
                      )}
                    </div>
                  )}
                </div>

                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <FileText size={12} />
                    <span className="text-[10px] font-bold uppercase tracking-wider">Source Documents</span>
                  </div>
                  {mode === "read" && !isNew ? (
                    <div className="flex flex-wrap gap-1.5">
                      {selectedDocIds.length > 0 ? (
                        selectedDocIds.map((id) => {
                          const doc = documents.find((d) => d.id === id)
                          return (
                            <div key={id} className="rounded bg-muted px-2 py-0.5 text-xs truncate max-w-[200px]">
                              {doc?.title ?? id}
                            </div>
                          )
                        })
                      ) : (
                        <span className="text-xs text-muted-foreground italic">No source documents</span>
                      )}
                    </div>
                  ) : (
                    <div className="max-h-40 overflow-y-auto flex flex-col gap-1">
                      {documents.map((doc) => (
                        <label
                          key={doc.id}
                          className="flex items-center gap-2 cursor-pointer rounded px-1 py-0.5 text-xs text-foreground hover:bg-accent/50"
                        >
                          <input
                            type="checkbox"
                            checked={selectedDocIds.includes(doc.id)}
                            onChange={(e) => {
                              setSelectedDocIds((prev) =>
                                e.target.checked ? [...prev, doc.id] : prev.filter((id) => id !== doc.id)
                              )
                            }}
                            className="h-3 w-3 rounded border-border"
                          />
                          <span className="truncate">{doc.title}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="shrink-0 border-t border-border bg-background px-6 py-4 flex items-center gap-3">
          {mode === "read" && !isNew ? (
            confirmDelete ? (
              <div className="flex flex-1 items-center justify-end gap-3">
                <span className="text-xs text-muted-foreground">Delete note forever?</span>
                <button
                  onClick={() => deleteMut.mutate()}
                  disabled={deleteMut.isPending}
                  className="rounded bg-destructive px-3 py-1.5 text-xs font-medium text-white hover:bg-destructive/90 disabled:opacity-50"
                >
                  Confirm Delete
                </button>
                <button
                  onClick={() => setConfirmDelete(false)}
                  className="rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <>
                <button
                  onClick={onClose}
                  className="rounded border border-border bg-background px-4 py-2 text-xs text-muted-foreground hover:bg-accent transition-colors"
                >
                  Close
                </button>
                <div className="flex-1" />
                <button
                  onClick={() => setConfirmDelete(true)}
                  className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground hover:text-destructive hover:border-destructive transition-colors"
                  title="Delete Note"
                >
                  <Trash2 size={14} />
                </button>
                <button
                  onClick={() => setMode("edit")}
                  className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 shadow-sm transition-colors"
                >
                  <Pencil size={14} />
                  Edit Note
                </button>
              </>
            )
          ) : (
            <>
              <div className="mr-auto flex items-center gap-2 text-[10px] text-muted-foreground">
                <kbd className="rounded border bg-muted px-1">Ctrl+S</kbd> to save
              </div>
              <button
                onClick={handleCancelEdit}
                className="rounded border border-border bg-background px-4 py-2 text-xs text-muted-foreground hover:bg-accent shadow-sm transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => saveMut.mutate()}
                disabled={!editContent.trim() || saveMut.isPending}
                className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 shadow-sm transition-colors"
              >
                {saveMut.isPending ? "Saving..." : isNew ? "Create Note" : "Save Changes"}
              </button>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
