/**
 * NotesReaderPanel -- S192: collection-scoped active reading sidebar.
 *
 * Shows notes from the document's auto-collection in the right panel of DocumentReader.
 * Clicking edit / double-click opens the full NoteReaderSheet (same as Notes tab).
 * The book's auto-collection is shown checked and locked in the sheet.
 */

import { useEffect, useState, useCallback } from "react"
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query"
import { Loader2, Plus, Pencil, Trash2, BookOpen } from "lucide-react"
import { toast } from "sonner"
import { API_BASE } from "@/lib/config"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { NoteReaderSheet } from "@/components/NoteReaderSheet"

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
  collection_ids: string[]
  source_document_ids: string[]
  chunk_id: string | null
  group_name: string | null
  created_at: string
  updated_at: string
}

interface SectionInfo {
  id: string
  heading: string
  section_order: number
}

interface DocumentItem {
  id: string
  title: string
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

async function fetchDocuments(): Promise<DocumentItem[]> {
  const res = await fetch(`${API_BASE}/documents?page_size=200`)
  if (!res.ok) return []
  const data = (await res.json()) as { items: DocumentItem[] }
  return data.items ?? []
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
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)

  // Sheet state: which note is open for viewing/editing
  const [sheetNote, setSheetNote] = useState<NoteItem | null>(null)
  const [sheetIsNew, setSheetIsNew] = useState(false)

  // Step 1: fetch auto-collection if it exists
  useEffect(() => {
    let cancelled = false
    async function ensure() {
      try {
        const col = await fetchAutoCollection(documentId)
        if (!cancelled && col) {
          setCollectionId(col.id)
        }
      } catch {
        // silently fail
      } finally {
        if (!cancelled) setEnsured(true)
      }
    }
    void ensure()
    return () => { cancelled = true }
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

  // Step 3: fetch sections for sort + heading display
  const { data: sections } = useQuery({
    queryKey: ["doc-sections", documentId],
    queryFn: () => fetchSections(documentId),
    staleTime: 60_000,
  })

  // Fetch documents list for NoteReaderSheet
  const { data: documents = [] } = useQuery({
    queryKey: ["documents-list-mini"],
    queryFn: fetchDocuments,
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

  // Sort notes by section_order (AC6)
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
      void qc.invalidateQueries({ queryKey: ["notes"] })
      toast.success("Note deleted")
    },
    onError: () => toast.error("Failed to delete note"),
  })

  function handleOpenNew() {
    setSheetNote({
      id: "",
      document_id: documentId,
      section_id: activeSectionId ?? null,
      content: "",
      tags: [],
      collection_ids: collectionId ? [collectionId] : [],
      source_document_ids: [documentId],
      chunk_id: null,
      group_name: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    })
    setSheetIsNew(true)
  }

  function handleOpenExisting(note: NoteItem) {
    setSheetNote(note)
    setSheetIsNew(false)
  }

  function handleSheetClose() {
    setSheetNote(null)
    setSheetIsNew(false)
  }

  const handleSheetSaved = useCallback((_savedNote: unknown) => {
    void qc.invalidateQueries({ queryKey: ["reader-notes", collectionId] })
    void qc.invalidateQueries({ queryKey: ["notes"] })
    if (sheetIsNew) {
      setSheetNote(null)
      setSheetIsNew(false)
    }
  }, [qc, collectionId, sheetIsNew])

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
      <button
        onClick={handleOpenNew}
        className="flex items-center gap-1.5 self-start rounded-md border border-dashed border-muted-foreground/30 px-3 py-1.5 text-xs text-muted-foreground hover:border-foreground/50 hover:text-foreground"
      >
        <Plus size={12} />
        Add note
      </button>

      {/* Notes list */}
      {notesLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 size={14} className="animate-spin" />
          Loading...
        </div>
      ) : sortedNotes.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No notes yet — start annotating as you read.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {sortedNotes.map((note) => (
            <div
              key={note.id}
              className="group rounded-md border border-muted p-2.5"
            >
              {/* Note card: markdown preview, double-click to open sheet */}
              <div
                className="cursor-text select-text"
                onDoubleClick={() => handleOpenExisting(note)}
                title="Double-click to edit"
              >
                <MarkdownRenderer className="prose-xs">{note.content}</MarkdownRenderer>
              </div>
              {/* Section heading link */}
              {note.section_id && onScrollToSection && (
                <button
                  onClick={() => onScrollToSection(note.section_id!)}
                  className="mt-1 flex items-center gap-1 text-[10px] text-primary hover:underline"
                >
                  <BookOpen size={10} />
                  {sectionHeadingMap.get(note.section_id) ?? "Go to section"}
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
                  {new Date(note.created_at).toLocaleDateString()}
                </span>
                <div className="flex gap-1 sm:opacity-0 sm:group-hover:opacity-100">
                  <button
                    title="Edit"
                    onClick={() => handleOpenExisting(note)}
                    className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    <Pencil size={12} />
                  </button>
                  {deleteConfirmId === note.id ? (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => void deleteMut.mutate(note.id)}
                        className="rounded bg-red-500 px-2 py-0.5 text-[10px] text-white"
                      >
                        {deleteMut.isPending ? "..." : "Confirm"}
                      </button>
                      <button
                        onClick={() => setDeleteConfirmId(null)}
                        className="text-[10px] text-muted-foreground hover:text-foreground"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      title="Delete"
                      onClick={() => setDeleteConfirmId(note.id)}
                      className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-red-500"
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* NoteReaderSheet — reuses the full Notes tab editor */}
      <NoteReaderSheet
        note={sheetNote}
        documents={documents}
        onClose={handleSheetClose}
        onSaved={handleSheetSaved}
        isNew={sheetIsNew}
        lockedCollectionId={collectionId}
      />
    </div>
  )
}
