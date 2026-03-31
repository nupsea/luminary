/**
 * NotesReaderPanel -- S192: collection-scoped active reading sidebar.
 *
 * Shows notes from the document's auto-collection in the right panel of DocumentReader.
 * Supports inline add/edit/delete and click-to-scroll-to-section.
 */

import { useEffect, useState, useCallback } from "react"
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query"
import { Loader2, Plus, Pencil, Trash2, BookOpen } from "lucide-react"
import { toast } from "sonner"
import { stripMarkdown } from "@/lib/utils"
import { API_BASE } from "@/lib/config"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AutoCollection {
  id: string
  name: string
  auto_document_id: string | null
}

interface NoteItem {
  id: string
  document_id: string | null
  section_id: string | null
  content: string
  tags: string[]
  created_at: string
  updated_at: string
}

interface SectionInfo {
  id: string
  heading: string
  section_order: number
}

interface NotesReaderPanelProps {
  documentId: string
  activeSectionId: string | null
  onScrollToSection?: (sectionId: string) => void
  /** Called when the initial note count is known, so parent can set default tab */
  onNoteCountKnown?: (count: number) => void
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchAutoCollection(
  documentId: string,
): Promise<AutoCollection | null> {
  const res = await fetch(
    `${API_BASE}/collections/by-document/${documentId}`,
  )
  if (res.status === 404) return null
  if (!res.ok) throw new Error("Failed to fetch auto-collection")
  return res.json() as Promise<AutoCollection>
}

async function createAutoCollection(
  documentId: string,
): Promise<AutoCollection> {
  const res = await fetch(
    `${API_BASE}/collections/auto/${documentId}`,
    { method: "POST" },
  )
  if (!res.ok) throw new Error("Failed to create auto-collection")
  return res.json() as Promise<AutoCollection>
}

async function fetchNotes(collectionId: string): Promise<NoteItem[]> {
  const res = await fetch(
    `${API_BASE}/notes?collection_id=${collectionId}`,
  )
  if (!res.ok) throw new Error("Failed to fetch notes")
  return res.json() as Promise<NoteItem[]>
}

async function fetchSections(
  documentId: string,
): Promise<SectionInfo[]> {
  const res = await fetch(`${API_BASE}/documents/${documentId}`)
  if (!res.ok) return []
  const doc = (await res.json()) as {
    sections: SectionInfo[]
  }
  return doc.sections ?? []
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function NotesReaderPanel({
  documentId,
  activeSectionId,
  onScrollToSection,
  onNoteCountKnown,
}: NotesReaderPanelProps) {
  const qc = useQueryClient()
  const [collectionId, setCollectionId] = useState<string | null>(null)
  const [ensured, setEnsured] = useState(false)
  const [addingNote, setAddingNote] = useState(false)
  const [newNoteContent, setNewNoteContent] = useState("")
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null)
  const [editContent, setEditContent] = useState("")
  const [editTags, setEditTags] = useState<string[]>([])
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(
    null,
  )

  // Step 1: ensure auto-collection exists
  useEffect(() => {
    let cancelled = false
    async function ensure() {
      try {
        let col = await fetchAutoCollection(documentId)
        if (!col && !cancelled) {
          col = await createAutoCollection(documentId)
        }
        if (!cancelled && col) {
          setCollectionId(col.id)
        }
      } catch {
        // silently fail -- user can still use other tabs
      } finally {
        if (!cancelled) setEnsured(true)
      }
    }
    void ensure()
    return () => {
      cancelled = true
    }
  }, [documentId])

  // Step 2: fetch notes for the auto-collection
  const {
    data: notes,
    isLoading: notesLoading,
    isError,
  } = useQuery({
    queryKey: ["reader-notes", collectionId],
    queryFn: () => fetchNotes(collectionId!),
    enabled: !!collectionId,
    staleTime: 10_000,
  })

  // Step 3: fetch sections to get section_order for sorting
  const { data: sections } = useQuery({
    queryKey: ["doc-sections", documentId],
    queryFn: () => fetchSections(documentId),
    staleTime: 60_000,
  })

  // Notify parent of note count for default tab logic (AC5)
  useEffect(() => {
    if (notes !== undefined && onNoteCountKnown) {
      onNoteCountKnown(notes.length)
    }
  }, [notes, onNoteCountKnown])

  // Build section lookup maps
  const sectionOrderMap = new Map<string, number>()
  const sectionHeadingMap = new Map<string, string>()
  for (const sec of sections ?? []) {
    sectionOrderMap.set(sec.id, sec.section_order)
    sectionHeadingMap.set(sec.id, sec.heading)
  }

  // Sort notes by section_order (AC6): linked notes first by section_order,
  // unlinked notes at the end sorted by created_at.
  const sortedNotes = (notes ?? []).slice().sort((a, b) => {
    const aOrder = a.section_id
      ? sectionOrderMap.get(a.section_id) ?? Infinity
      : Infinity
    const bOrder = b.section_id
      ? sectionOrderMap.get(b.section_id) ?? Infinity
      : Infinity
    if (aOrder !== bOrder) return aOrder - bOrder
    return (
      new Date(a.created_at).getTime() -
      new Date(b.created_at).getTime()
    )
  })

  // Create note mutation
  const createMut = useMutation({
    mutationFn: async (content: string) => {
      const res = await fetch(`${API_BASE}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: documentId,
          section_id: activeSectionId ?? undefined,
          content,
          tags: [],
          group_name: null,
        }),
      })
      if (!res.ok) throw new Error("Failed to create note")
      const note = (await res.json()) as { id: string }
      // Add to auto-collection
      if (collectionId) {
        await fetch(
          `${API_BASE}/collections/${collectionId}/notes`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ note_ids: [note.id] }),
          },
        )
      }
      return note
    },
    onSuccess: () => {
      setAddingNote(false)
      setNewNoteContent("")
      void qc.invalidateQueries({
        queryKey: ["reader-notes", collectionId],
      })
      toast.success("Note saved")
    },
    onError: () => toast.error("Failed to save note"),
  })

  // Edit note mutation (AC9: sends content + tags)
  const editMut = useMutation({
    mutationFn: async ({
      noteId,
      content,
      tags,
    }: {
      noteId: string
      content: string
      tags: string[]
    }) => {
      const res = await fetch(`${API_BASE}/notes/${noteId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, tags }),
      })
      if (!res.ok) throw new Error("Failed to update note")
    },
    onSuccess: () => {
      setEditingNoteId(null)
      setEditContent("")
      setEditTags([])
      void qc.invalidateQueries({
        queryKey: ["reader-notes", collectionId],
      })
      toast.success("Note updated")
    },
    onError: () => toast.error("Failed to update note"),
  })

  // Delete note mutation
  const deleteMut = useMutation({
    mutationFn: async (noteId: string) => {
      const res = await fetch(`${API_BASE}/notes/${noteId}`, {
        method: "DELETE",
      })
      if (!res.ok) throw new Error("Failed to delete note")
    },
    onSuccess: () => {
      setDeleteConfirmId(null)
      void qc.invalidateQueries({
        queryKey: ["reader-notes", collectionId],
      })
      toast.success("Note deleted")
    },
    onError: () => toast.error("Failed to delete note"),
  })

  const handleStartEdit = useCallback((note: NoteItem) => {
    setEditingNoteId(note.id)
    setEditContent(note.content)
    setEditTags([...note.tags])
  }, [])

  // Loading state
  if (!ensured) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 size={14} className="animate-spin" />
        Loading notes...
      </div>
    )
  }

  if (isError) {
    return <p className="text-sm text-red-500">Failed to load notes.</p>
  }

  return (
    <div className="flex h-full flex-col gap-3">
      {/* Add note button */}
      {!addingNote && (
        <button
          onClick={() => setAddingNote(true)}
          className="flex items-center gap-1.5 self-start rounded-md border border-dashed border-muted-foreground/30 px-3 py-1.5 text-xs text-muted-foreground hover:border-foreground/50 hover:text-foreground"
        >
          <Plus size={12} />
          Add note
        </button>
      )}

      {/* Inline add editor */}
      {addingNote && (
        <div className="rounded-md border border-primary/30 p-2">
          <textarea
            autoFocus
            rows={3}
            placeholder="Write your note..."
            value={newNoteContent}
            onChange={(e) => setNewNoteContent(e.target.value)}
            className="w-full resize-none rounded border border-muted bg-transparent px-2 py-1.5 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-primary"
          />
          {activeSectionId && (
            <p className="mt-1 text-[10px] text-muted-foreground">
              Linked to current section
            </p>
          )}
          <div className="mt-2 flex gap-2">
            <button
              disabled={
                !newNoteContent.trim() || createMut.isPending
              }
              onClick={() =>
                void createMut.mutate(newNoteContent.trim())
              }
              className="rounded bg-primary px-3 py-1 text-xs font-medium text-primary-foreground disabled:opacity-50"
            >
              {createMut.isPending ? "Saving..." : "Save"}
            </button>
            <button
              onClick={() => {
                setAddingNote(false)
                setNewNoteContent("")
              }}
              className="rounded px-3 py-1 text-xs text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Notes list */}
      {notesLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 size={14} className="animate-spin" />
          Loading...
        </div>
      ) : sortedNotes.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No notes yet -- start annotating as you read.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {sortedNotes.map((note) => (
            <div
              key={note.id}
              className="group rounded-md border border-muted p-2.5"
            >
              {editingNoteId === note.id ? (
                /* Inline editor (AC9: full content + tags) */
                <div>
                  <textarea
                    autoFocus
                    rows={4}
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    className="w-full resize-none rounded border border-muted bg-transparent px-2 py-1.5 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                  {/* Tags editor */}
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {editTags.map((tag, i) => (
                      <span
                        key={tag}
                        className="flex items-center gap-0.5 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                      >
                        {tag}
                        <button
                          onClick={() =>
                            setEditTags((t) =>
                              t.filter((_, idx) => idx !== i),
                            )
                          }
                          className="ml-0.5 text-muted-foreground hover:text-foreground"
                        >
                          x
                        </button>
                      </span>
                    ))}
                    <input
                      placeholder="Add tag..."
                      className="w-16 bg-transparent text-[10px] outline-none placeholder:text-muted-foreground/50"
                      onKeyDown={(e) => {
                        if (
                          (e.key === "Enter" || e.key === ",") &&
                          e.currentTarget.value.trim()
                        ) {
                          e.preventDefault()
                          const val = e.currentTarget.value.trim()
                          if (!editTags.includes(val)) {
                            setEditTags((t) => [...t, val])
                          }
                          e.currentTarget.value = ""
                        }
                      }}
                    />
                  </div>
                  <div className="mt-2 flex gap-2">
                    <button
                      disabled={
                        !editContent.trim() || editMut.isPending
                      }
                      onClick={() =>
                        void editMut.mutate({
                          noteId: note.id,
                          content: editContent.trim(),
                          tags: editTags,
                        })
                      }
                      className="rounded bg-primary px-3 py-1 text-xs font-medium text-primary-foreground disabled:opacity-50"
                    >
                      {editMut.isPending ? "Saving..." : "Save"}
                    </button>
                    <button
                      onClick={() => {
                        setEditingNoteId(null)
                        setEditContent("")
                        setEditTags([])
                      }}
                      className="rounded px-3 py-1 text-xs text-muted-foreground hover:text-foreground"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                /* Note card */
                <>
                  <p className="line-clamp-2 text-xs text-foreground">
                    {stripMarkdown(note.content)}
                  </p>
                  {/* Section heading link */}
                  {note.section_id && onScrollToSection && (
                    <button
                      onClick={() =>
                        onScrollToSection(note.section_id!)
                      }
                      className="mt-1 flex items-center gap-1 text-[10px] text-primary hover:underline"
                    >
                      <BookOpen size={10} />
                      {sectionHeadingMap.get(note.section_id) ??
                        "Go to section"}
                    </button>
                  )}
                  {note.tags.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {note.tags.map((t) => (
                        <span
                          key={t}
                          className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="mt-1 flex items-center justify-between">
                    <span className="text-[10px] text-muted-foreground">
                      {new Date(
                        note.created_at,
                      ).toLocaleDateString()}
                    </span>
                    <div className="flex gap-1 sm:opacity-0 sm:group-hover:opacity-100">
                      <button
                        title="Edit"
                        onClick={() => handleStartEdit(note)}
                        className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        <Pencil size={12} />
                      </button>
                      {deleteConfirmId === note.id ? (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() =>
                              void deleteMut.mutate(note.id)
                            }
                            className="rounded bg-red-500 px-2 py-0.5 text-[10px] text-white"
                          >
                            {deleteMut.isPending
                              ? "..."
                              : "Confirm"}
                          </button>
                          <button
                            onClick={() =>
                              setDeleteConfirmId(null)
                            }
                            className="text-[10px] text-muted-foreground hover:text-foreground"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          title="Delete"
                          onClick={() =>
                            setDeleteConfirmId(note.id)
                          }
                          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-red-500"
                        >
                          <Trash2 size={12} />
                        </button>
                      )}
                    </div>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
