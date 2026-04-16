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
import { Link, Loader2, Tag } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { TagAutocomplete } from "@/components/TagAutocomplete"
import { LinkAutocomplete } from "@/components/LinkAutocomplete"
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
import { detectLinkTrigger, insertLinkAtTrigger } from "@/lib/noteLinkUtils"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Note {
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
  status: string
}

interface NoteLinkItem {
  id: string
  note_id: string
  preview: string
  link_type: string
  created_at: string
}

interface NoteLinksResponse {
  outgoing: NoteLinkItem[]
  incoming: NoteLinkItem[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function patchNote(
  id: string,
  data: { content?: string; tags?: string[]; group_name?: string; source_document_ids?: string[] },
): Promise<Note> {
  const res = await fetch(`${API_BASE}/notes/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`PATCH /notes/${id} failed: ${res.status}`)
  return res.json() as Promise<Note>
}

async function fetchDocuments(): Promise<DocumentItem[]> {
  const res = await fetch(`${API_BASE}/documents`)
  if (!res.ok) return []
  const docs = (await res.json()) as DocumentItem[]
  return docs.filter((d) => d.status === "ready")
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
  const res = await fetch(`${API_BASE}/collections/${collectionId}/members`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ member_ids: [noteId], member_type: "note" }),
  })
  if (!res.ok) throw new Error(`POST /collections/${collectionId}/members failed`)
}

async function removeNoteFromCollection(collectionId: string, noteId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/collections/${collectionId}/members/${noteId}`, {
    method: "DELETE",
  })
  if (!res.ok && res.status !== 204)
    throw new Error(`DELETE /collections/${collectionId}/members/${noteId} failed`)
}

async function fetchNoteLinks(noteId: string): Promise<NoteLinksResponse> {
  const res = await fetch(`${API_BASE}/notes/${noteId}/links`)
  if (!res.ok) return { outgoing: [], incoming: [] }
  return res.json() as Promise<NoteLinksResponse>
}

async function createNoteLink(
  noteId: string,
  targetNoteId: string,
  linkType: string,
): Promise<NoteLinkItem> {
  const res = await fetch(`${API_BASE}/notes/${noteId}/links`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_note_id: targetNoteId, link_type: linkType }),
  })
  if (!res.ok) throw new Error(`POST /notes/${noteId}/links failed: ${res.status}`)
  return res.json() as Promise<NoteLinkItem>
}

async function deleteNoteLink(
  noteId: string,
  targetNoteId: string,
  linkType: string,
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/notes/${noteId}/links/${targetNoteId}?link_type=${encodeURIComponent(linkType)}`,
    { method: "DELETE" },
  )
  if (!res.ok && res.status !== 204)
    throw new Error(`DELETE /notes/${noteId}/links/${targetNoteId} failed`)
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
  // S175: source document IDs (multi-select)
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>(
    note?.source_document_ids ?? (note?.document_id ? [note.document_id] : []),
  )
  // Link autocomplete state
  const [linkQuery, setLinkQuery] = useState<string | null>(null)
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

  // S175: documents list for source picker
  const { data: documents, isLoading: docsLoading } = useQuery({
    queryKey: ["documents-list"],
    queryFn: fetchDocuments,
    staleTime: 60_000,
    enabled: note !== null,
  })

  // Note links query (S171)
  const { data: noteLinks, isLoading: linksLoading } = useQuery({
    queryKey: ["note-links", note?.id],
    queryFn: () => fetchNoteLinks(note!.id),
    staleTime: 10_000,
    enabled: note !== null,
  })

  const deleteLinkMut = useMutation({
    mutationFn: ({ targetId, linkType }: { targetId: string; linkType: string }) =>
      deleteNoteLink(note!.id, targetId, linkType),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["note-links", note?.id] })
    },
  })

  const createLinkMut = useMutation({
    mutationFn: ({ targetId, linkType }: { targetId: string; linkType: string }) =>
      createNoteLink(note!.id, targetId, linkType),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["note-links", note?.id] })
    },
  })

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
      setSelectedDocIds(
        note.source_document_ids?.length > 0
          ? note.source_document_ids
          : note.document_id
            ? [note.document_id]
            : [],
      )
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
    setLinkQuery(null)
    onClose()
  }

  const saveMut = useMutation({
    mutationFn: () => patchNote(note!.id, { content, tags: editTags, source_document_ids: selectedDocIds }),
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
            <div className="relative flex-1 min-h-0">
              <textarea
                ref={textareaRef}
                value={content}
                onChange={(e) => {
                  setContent(e.target.value)
                  setIsSaved(false)
                  const query = detectLinkTrigger(e.target.value, e.target.selectionStart)
                  setLinkQuery(query)
                }}
                onBlur={() => {
                  // Delay so onMouseDown on LinkAutocomplete item fires first
                  setTimeout(() => setLinkQuery(null), 200)
                }}
                className="h-full w-full resize-none bg-background px-4 py-3 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
                placeholder="Write your note in Markdown... Type [[ to link a note"
              />
              {linkQuery !== null && (
                <LinkAutocomplete
                  query={linkQuery}
                  onSelect={(id, preview, selectedLinkType) => {
                    if (!textareaRef.current) return
                    const { newValue, newCursorPos } = insertLinkAtTrigger(
                      content,
                      textareaRef.current.selectionStart,
                      id,
                      preview,
                    )
                    setContent(newValue)
                    setLinkQuery(null)
                    // Also create the structured link row (fire-and-forget, ignore 409)
                    if (note?.id) {
                      createLinkMut.mutate({ targetId: id, linkType: selectedLinkType })
                    }
                    // Restore cursor position
                    setTimeout(() => {
                      textareaRef.current?.setSelectionRange(newCursorPos, newCursorPos)
                      textareaRef.current?.focus()
                    }, 0)
                  }}
                  onClose={() => setLinkQuery(null)}
                />
              )}
            </div>
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

            {/* Source documents section (S175) */}
            <div className="shrink-0 border-t border-border px-4 py-2">
              <p className="mb-1 text-xs font-medium text-muted-foreground">Source documents</p>
              {docsLoading ? (
                <div className="flex flex-col gap-1">
                  {Array.from({ length: 2 }).map((_, i) => (
                    <Skeleton key={i} className="h-5 w-full rounded" />
                  ))}
                </div>
              ) : (documents ?? []).length === 0 ? (
                <p className="text-xs text-muted-foreground">Ingest a book to link notes to it</p>
              ) : (
                <div className="max-h-32 overflow-y-auto flex flex-col gap-0.5">
                  {(documents ?? []).map((doc) => (
                    <label
                      key={doc.id}
                      className="flex items-center gap-2 cursor-pointer rounded px-1 py-0.5 text-xs text-foreground hover:bg-accent/50"
                    >
                      <input
                        type="checkbox"
                        checked={selectedDocIds.includes(doc.id)}
                        onChange={(e) => {
                          setSelectedDocIds((prev) =>
                            e.target.checked
                              ? [...prev, doc.id]
                              : prev.filter((id) => id !== doc.id),
                          )
                          setIsSaved(false)
                        }}
                        className="h-3 w-3 rounded border-border"
                      />
                      <span className="flex-1 truncate">{doc.title}</span>
                    </label>
                  ))}
                </div>
              )}
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
            {/* Links section (S171) */}
            <div className="shrink-0 border-t border-border px-4 py-2">
              <p className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground">
                <Link size={11} />
                Links
              </p>
              {linksLoading ? (
                <Skeleton className="h-4 w-24 rounded" />
              ) : (
                <div className="flex flex-col gap-1">
                  {(noteLinks?.outgoing ?? []).length === 0 &&
                    (noteLinks?.incoming ?? []).length === 0 && (
                      <p className="text-xs text-muted-foreground">No links yet. Type [[ to link.</p>
                    )}
                  {(noteLinks?.outgoing ?? []).length > 0 && (
                    <div className="flex flex-col gap-0.5">
                      <span className="text-xs text-muted-foreground">Outgoing</span>
                      {noteLinks!.outgoing.map((link) => (
                        <div key={link.id} className="flex items-center gap-1.5 rounded px-1 py-0.5 text-xs bg-indigo-50 border border-indigo-200">
                          <span className="rounded-full bg-indigo-200 px-1 text-[10px] text-indigo-700">{link.link_type}</span>
                          <span className="flex-1 truncate text-foreground">{link.preview}</span>
                          <button
                            onClick={() => deleteLinkMut.mutate({ targetId: link.note_id, linkType: link.link_type })}
                            className="text-muted-foreground hover:text-destructive"
                            title="Remove link"
                          >
                            &times;
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  {(noteLinks?.incoming ?? []).length > 0 && (
                    <div className="flex flex-col gap-0.5">
                      <span className="text-xs text-muted-foreground">Backlinks</span>
                      {noteLinks!.incoming.map((link) => (
                        <div key={link.id} className="flex items-center gap-1.5 rounded px-1 py-0.5 text-xs bg-muted border border-border">
                          <span className="rounded-full bg-muted-foreground/20 px-1 text-[10px] text-muted-foreground">{link.link_type}</span>
                          <span className="flex-1 truncate text-foreground">{link.preview}</span>
                        </div>
                      ))}
                    </div>
                  )}
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
                <MarkdownRenderer
                  validNoteIds={
                    noteLinks !== undefined
                      ? new Set(noteLinks.outgoing.map((l) => l.note_id))
                      : undefined
                  }
                >
                  {content}
                </MarkdownRenderer>
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
