import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { CreateCollectionDialog } from "@/components/CreateCollectionDialog"
import { GapDetectDialog } from "@/components/GapDetectDialog"
import { type NamingViolation } from "@/components/OrganizationPlanDialog"
import { GenerateFlashcardsDialog } from "@/components/GenerateFlashcardsDialog"
import { NoteReaderSheet } from "@/components/NoteReaderSheet"
import { useDebounce } from "@/hooks/useDebounce"
import { ViewToggle } from "@/components/library/ViewToggle"
import { logger } from "@/lib/logger"
import { API_BASE } from "@/lib/config"
import { useAppStore } from "@/store"

import { NotesPanel } from "./Notes/NotesPanel"
import { NotesSidebar } from "./Notes/NotesSidebar"
import {
  createNoteFromClip,
  fetchClusterSuggestions,
  fetchDocumentList,
  fetchGroups,
  fetchNamingViolations,
  fetchNoteSearch,
  fetchNotes,
  postCluster,
} from "./Notes/api"
import type { Clip, CollectionTreeNode, Note } from "./Notes/types"






// ---------------------------------------------------------------------------
// Main Notes page
// ---------------------------------------------------------------------------

type FilterState =
  | { type: "all" }
  | { type: "journal" }
  | { type: "group"; name: string }
  | { type: "tag"; name: string }

export default function NotesPage() {
  const [filter, setFilter] = useState<FilterState>({ type: "all" })
  const [isCreating, setIsCreating] = useState(false)
  const [editingNote, setEditingNote] = useState<Note | null>(null)
  const [showGenerateFlashcards, setShowGenerateFlashcards] = useState(false)
  const [showGapDetect, setShowGapDetect] = useState(false)
  const [showCreateCollection, setShowCreateCollection] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const [isClusterQueued, setIsClusterQueued] = useState(false)
  const [showOrgPlan, setShowOrgPlan] = useState(false)
  const debouncedQuery = useDebounce(searchQuery, 300)
  const qc = useQueryClient()
  const mountTime = useRef(0)
  const notesView = useAppStore((s) => s.notesView)
  const setNotesView = useAppStore((s) => s.setNotesView)
  const activeCollectionId = useAppStore((s) => s.activeCollectionId)
  const setActiveCollectionId = useAppStore((s) => s.setActiveCollectionId)
  const activeTag = useAppStore((s) => s.activeTag)
  const setActiveTag = useAppStore((s) => s.setActiveTag)
  const notesDocumentId = useAppStore((s) => s.notesDocumentId)
  const setNotesDocumentId = useAppStore((s) => s.setNotesDocumentId)
  const notePreload = useAppStore((s) => s.notePreload)
  const setNotePreload = useAppStore((s) => s.setNotePreload)
  const navigate = useNavigate()

  useEffect(() => {
    mountTime.current = Date.now()
    logger.info("[Notes] mounted")
  }, [])

  useEffect(() => {
    if (notePreload) {
      queueMicrotask(() => {
        setIsCreating(true)
        setNotePreload(null)
      })
    }
  }, [notePreload, setNotePreload])

  const { data: groups } = useQuery({
    queryKey: ["notes-groups"],
    queryFn: fetchGroups,
  })

  const { data: documents = [] } = useQuery({
    queryKey: ["notes-documents"],
    queryFn: fetchDocumentList,
    staleTime: 60_000,
  })

  const { data: tree } = useQuery({
    queryKey: ["collections-tree"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/collections/tree`)
      return (await res.json()) as CollectionTreeNode[]
    },
    staleTime: 30_000,
  })

  const getCollectionName = (id: string) => {
    if (!tree) return id.slice(0, 8) + "..."
    const flat = (items: CollectionTreeNode[]): CollectionTreeNode[] =>
      items.flatMap((item) => [item, ...flat(item.children ?? [])])
    const found = flat(tree).find(i => i.id === id)
    return found ? found.name : id.slice(0, 8) + "..."
  }

  const groupParam = filter.type === "group" ? filter.name : undefined
  // activeTag from store takes precedence over sidebar filter tag
  const tagParam = activeTag ?? (filter.type === "tag" ? filter.name : undefined)
  // When a collection is active, clear group/tag params and use collection filter instead.
  const collectionParam = activeCollectionId ?? undefined

  const {
    data: notes,
    isLoading: notesLoading,
    isError: notesError,
    refetch,
  } = useQuery({
    queryKey: ["notes", groupParam, tagParam, collectionParam, notesDocumentId],
    queryFn: () => fetchNotes(notesDocumentId ?? undefined, groupParam, tagParam, collectionParam),
    gcTime: 60_000,
  })

  const {
    data: searchData,
    isLoading: searchLoading,
    isError: searchError,
    refetch: refetchSearch,
  } = useQuery({
    queryKey: ["notes-search", debouncedQuery],
    queryFn: () => fetchNoteSearch(debouncedQuery),
    enabled: debouncedQuery.trim().length > 0,
    staleTime: 10_000,
  })

  const isSearchMode = debouncedQuery.trim().length > 0

  const {
    data: clusterSuggestions = [],
    isLoading: clusterSuggestionsLoading,
    isError: clusterSuggestionsError,
    refetch: refetchClusterSuggestions,
  } = useQuery({
    queryKey: ["clusterSuggestions"],
    queryFn: fetchClusterSuggestions,
    staleTime: 30_000,
  })

  const [namingViolations, setNamingViolations] = useState<NamingViolation[]>([])

  async function handleAutoOrganize() {
    setIsClusterQueued(true)
    try {
      const [clusterResult, violations] = await Promise.all([
        postCluster(),
        fetchNamingViolations().catch(() => [] as NamingViolation[]),
      ])
      setNamingViolations(violations)

      if (clusterResult.cached) {
        setIsClusterQueued(false)
        setShowOrgPlan(true)
        return
      }
      setTimeout(() => {
        void qc.invalidateQueries({ queryKey: ["clusterSuggestions"] }).then(() => {
          setIsClusterQueued(false)
          setShowOrgPlan(true)
        })
      }, 3000)
    } catch {
      toast.error("Failed to start auto-organize")
      setIsClusterQueued(false)
    }
  }

  useEffect(() => {
    if (!notesLoading) {
      const elapsed = Date.now() - mountTime.current
      logger.info("[Notes] loaded", { duration_ms: elapsed, itemCount: notes?.length ?? 0 })
    }
  }, [notesLoading, notes?.length])

  function handleRefetch() {
    void qc.invalidateQueries({ queryKey: ["notes"] })
    void qc.invalidateQueries({ queryKey: ["notes-groups"] })
    void qc.invalidateQueries({ queryKey: ["collections-tree"] })
  }

  async function handleConvertClipToNote(clip: Clip) {
    const docTitle = documents.find((d) => d.id === clip.document_id)?.title ?? clip.document_id
    try {
      await createNoteFromClip(clip, docTitle)
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["notes-groups"] })
      toast.success("Note created from clip")
    } catch {
      toast.error("Failed to create note")
    }
  }

  async function handleCreateFlashcardFromClip(clip: Clip) {
    const docTitle = documents.find((d) => d.id === clip.document_id)?.title ?? clip.document_id
    try {
      await createNoteFromClip(clip, docTitle)
      void qc.invalidateQueries({ queryKey: ["notes"] })
      toast.success("Note created from clip — select it in the dialog to generate flashcards")
      setShowGenerateFlashcards(true)
    } catch {
      // still open the dialog even if note creation fails
      setShowGenerateFlashcards(true)
    }
  }

  const noteList = notes ?? []

  // Determine right panel content

  return (
    <div className="flex h-full overflow-hidden">
      <NotesSidebar
        filter={filter}
        onSetFilter={setFilter}
        activeCollectionId={activeCollectionId}
        onSetActiveCollectionId={setActiveCollectionId}
        activeTag={activeTag}
        onSetActiveTag={setActiveTag}
        groups={groups}
        fallbackNoteCount={noteList.length}
        onShowCreateCollection={() => setShowCreateCollection(true)}
        clusterSuggestions={clusterSuggestions}
        isClusterQueued={isClusterQueued}
        clusterSuggestionsLoading={clusterSuggestionsLoading}
        clusterSuggestionsError={Boolean(clusterSuggestionsError)}
        onAutoOrganize={() => void handleAutoOrganize()}
        onRefetchClusterSuggestions={() => void refetchClusterSuggestions()}
        showOrgPlan={showOrgPlan}
        onSetShowOrgPlan={setShowOrgPlan}
        namingViolations={namingViolations}
      />

      <div className="flex-1 overflow-auto p-6">
        <div className="mb-4 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-foreground">
            {notesDocumentId
              ? `Document: ${documents.find((d) => d.id === notesDocumentId)?.title ?? "..."}`
              : activeCollectionId
                ? `Collection: ${getCollectionName(activeCollectionId)}`
                : activeTag
                  ? `Tag: #${activeTag}`
                  : filter.type === "all"
                    ? "All Notes"
                    : filter.type === "journal"
                      ? "Reading Journal"
                      : filter.type === "group"
                        ? filter.name
                        : `#${filter.name}`}
          </h2>
          {notesDocumentId && (
            <button
              onClick={() => setNotesDocumentId(null)}
              className="rounded-full bg-accent px-2 py-0.5 text-xs text-accent-foreground hover:bg-primary/20 transition-colors flex items-center gap-1"
            >
              Clear document filter
              <X size={10} />
            </button>
          )}
          {filter.type !== "journal" && (
            <div className="flex items-center gap-2">
              <div className="relative">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search notes..."
                  className="rounded border border-border bg-background px-3 py-1 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary w-48 pr-7"
                />
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery("")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    title="Clear search"
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
              <ViewToggle value={notesView} onChange={setNotesView} />
              <button
                onClick={() => setShowGapDetect(true)}
                className="flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs text-foreground hover:bg-accent"
                title="Compare notes with a book to find gaps"
              >
                Compare with Book
              </button>
              <button
                onClick={() => setShowGenerateFlashcards(true)}
                className="flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs text-foreground hover:bg-accent"
                title="Generate flashcards from notes"
              >
                Generate Flashcards
              </button>
              <button
                onClick={() => setIsCreating(true)}
                className="flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs text-foreground hover:bg-accent"
                title="New note"
              >
                <Plus size={13} />
                New
              </button>
            </div>
          )}
        </div>

        <NotesPanel
          filter={filter}
          isSearchMode={isSearchMode}
          searchData={searchData}
          searchLoading={searchLoading}
          searchError={Boolean(searchError)}
          onRefetchSearch={() => void refetchSearch()}
          debouncedQuery={debouncedQuery}
          notesLoading={notesLoading}
          notesError={Boolean(notesError)}
          onRefetchNotes={() => void refetch()}
          noteList={noteList}
          notesView={notesView}
          documents={documents}
          activeTag={activeTag}
          onSetEditingNote={setEditingNote}
          onStartCreating={() => setIsCreating(true)}
          onConvertClipToNote={handleConvertClipToNote}
          onCreateFlashcardFromClip={handleCreateFlashcardFromClip}
          onDeleted={handleRefetch}
          navigate={navigate}
        />
      </div>

      <NoteReaderSheet
        note={editingNote}
        isNew={isCreating}
        initialContent={notePreload?.content}
        initialCollectionId={notePreload?.collectionId}
        documents={documents}
        onClose={() => {
          setEditingNote(null)
          setIsCreating(false)
        }}
        onSaved={(savedNote) => {
          void qc.invalidateQueries({ queryKey: ["notes"] })
          void qc.invalidateQueries({ queryKey: ["notes-groups"] })
          void qc.invalidateQueries({ queryKey: ["collections-tree"] })
          
          if (isCreating && activeCollectionId) {
            // If we're inside a collection, add the new note to it immediately
            void fetch(`${API_BASE}/collections/${activeCollectionId}/members`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ member_ids: [savedNote.id], member_type: "note" }),
            }).then(() => {
              void qc.invalidateQueries({ queryKey: ["notes"] })
              void qc.invalidateQueries({ queryKey: ["notes-groups"] })
              void qc.invalidateQueries({ queryKey: ["collections-tree"] })
            })
          }

          setEditingNote(savedNote)
          setIsCreating(false)
        }}
      />

      {/* GenerateFlashcardsDialog */}
      <GenerateFlashcardsDialog
        open={showGenerateFlashcards}
        onClose={() => setShowGenerateFlashcards(false)}
        availableTags={(groups?.tags ?? []).map((t) => t.name)}
      />

      {/* GapDetectDialog */}
      <GapDetectDialog
        open={showGapDetect}
        onClose={() => setShowGapDetect(false)}
      />

      {/* CreateCollectionDialog */}
      <CreateCollectionDialog
        open={showCreateCollection}
        onClose={() => setShowCreateCollection(false)}
      />
    </div>
  )
}
