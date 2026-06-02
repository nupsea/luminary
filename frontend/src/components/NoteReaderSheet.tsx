/**
 * NoteReaderSheet -- full-width reader/editor panel for notes.
 */

import { useEffect, useMemo, useRef, useState } from "react"
import {
  Check,
  ChevronsLeft,
  ChevronsRight,
  FileText,
  LayoutGrid,
  Pencil,
  Search,
  Tag,
  Trash2,
  X,
} from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { NoteEditor } from "@/components/notes/NoteEditor"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet } from "@/lib/apiClient"
import { flattenCollectionTree } from "@/lib/collectionUtils"
import { useNoteSaveShortcut } from "@/lib/noteEditorUtils"
import { stripMarkdown } from "@/lib/utils"
import { dispatchTagNavigate } from "@/lib/noteNavigateUtils"
import {
  addNoteToCollection,
  createNote,
  deleteNote,
  fetchCollectionTree,
  fetchSuggestedTags,
  patchNote,
  removeNoteFromCollection,
  suggestNoteTitle,
  type Note,
} from "@/lib/notesApi"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DocumentItem {
  id: string
  title: string
}

interface ExistingNoteSummary {
  id: string
  content: string
  tags: string[]
  updated_at: string
}

function firstLine(content: string): string {
  const line = content.split("\n").find((l) => l.trim().length > 0) ?? ""
  return line.length > 80 ? line.slice(0, 80) + "..." : line
}

function formatRelative(dateStr: string): string {
  const date = new Date(dateStr)
  const diffMs = Date.now() - date.getTime()
  const mins = Math.floor(diffMs / 60_000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return date.toLocaleDateString()
}

export interface NoteReaderSheetProps {
  note: Note | null
  documents: DocumentItem[]
  onClose: () => void
  onSaved: (note: Note) => void
  isNew?: boolean
  /** S197: Pre-fill content when creating a note from gap analysis. */
  initialContent?: string
  /** S197: Pre-check a collection when creating a note from gap analysis. */
  initialCollectionId?: string
  /** Pre-select these source documents when creating a new note. */
  initialSourceDocIds?: string[]
  /** When set, this collection appears checked and cannot be unchecked (reader context). */
  lockedCollectionId?: string | null
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
  initialContent,
  initialCollectionId,
  initialSourceDocIds,
  lockedCollectionId,
}: NoteReaderSheetProps) {
  const [mode, setMode] = useState<"read" | "edit">(isNew ? "edit" : "read")
  // Per-open state; not persisted.
  const [wideMode, setWideMode] = useState(false)
  const [editContent, setEditContent] = useState("")
  const [editTags, setEditTags] = useState<string[]>([])
  const [checkedCollectionIds, setCheckedCollectionIds] = useState<Set<string>>(new Set())
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [suggestedTags, setSuggestedTags] = useState<string[]>([])
  const [isFetchingTags, setIsFetchingTags] = useState(false)
  const [generatedTitle, setGeneratedTitle] = useState("")
  const [isGeneratingTitle, setIsGeneratingTitle] = useState(false)
  const [titleEditing, setTitleEditing] = useState(false)
  const [titleDraft, setTitleDraft] = useState("")
  const abortRef = useRef<AbortController | null>(null)
  const prevNoteId = useRef<string | undefined>(undefined)
  const prevIsNew = useRef<boolean>(false)
  const qc = useQueryClient()

  const [appendTarget, setAppendTarget] = useState<ExistingNoteSummary | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerFilter, setPickerFilter] = useState("")
  const [existingNotes, setExistingNotes] = useState<ExistingNoteSummary[]>([])
  const [notesLoading, setNotesLoading] = useState(false)

  useEffect(() => {
    if (isNew) {
      setEditContent(initialContent ?? "")
      setEditTags([])
      setCheckedCollectionIds(initialCollectionId ? new Set([initialCollectionId]) : new Set())
      setSelectedDocIds(initialSourceDocIds ?? [])
      setMode("edit")
      setConfirmDelete(false)
      setSuggestedTags([])
      setIsFetchingTags(false)
      setAppendTarget(null)
      setPickerOpen(false)
      setPickerFilter("")
      // Reset stale title state so a previously-generated title doesn't bleed
      // into the next new-note open. The title effect will set "New Note"
      // synchronously below.
      setGeneratedTitle("")
      setIsGeneratingTitle(false)
      setTitleEditing(false)
      setTitleDraft("")
      prevIsNew.current = true
    } else if (note) {
      setEditContent(note.content)
      setEditTags(note.tags ?? [])
      setCheckedCollectionIds(new Set((note.collections ?? []).map((c) => c.id)))
      setSelectedDocIds(
        note.source_document_ids?.length > 0
          ? note.source_document_ids
          : note.document_id
            ? [note.document_id]
            : [],
      )
      setMode("read")
      setConfirmDelete(false)

      // Only clear suggestions if we're switching to a genuinely different existing note.
      // Crucially, if we just transitioned from isNew=true to an actual note,
      // we DON'T clear suggestions because they were likely just fetched by saveMut.
      const justSaved = prevIsNew.current && !isNew
      const noteChanged = prevNoteId.current && prevNoteId.current !== note.id

      if (noteChanged && !justSaved) {
        setSuggestedTags([])
        setIsFetchingTags(false)
      }
      
      prevNoteId.current = note.id
      prevIsNew.current = isNew
    }
  }, [note?.id, isNew])

  // Resolve the displayed title.
  // 1. If the user has manually set a title (note.title_auto_generated === false),
  //    use it verbatim and skip the LLM call entirely. Manual titles are sacred.
  // 2. Otherwise on existing notes, run the LLM auto-gen path that already
  //    existed -- falling back to the first content line on failure.
  // 3. On new (unsaved) notes, show "New Note" so the previous note's title
  //    doesn't linger when the sheet re-opens for a fresh capture.
  useEffect(() => {
    if (isNew) {
      setGeneratedTitle("New Note")
      setIsGeneratingTitle(false)
      return
    }
    if (note && note.title) {
      setGeneratedTitle(note.title)
      setIsGeneratingTitle(false)
      return
    }
    if (note && note.content) {
      if (note.content.trim().length > 20) {
        setIsGeneratingTitle(true)
        suggestNoteTitle(note.content)
          .then((title) => {
            setGeneratedTitle(title)
            setIsGeneratingTitle(false)
            // Save it back to the db so it doesn't keep regenerating
            void patchNote(note.id, { title }).then(() => {
              void qc.invalidateQueries({ queryKey: ["notes"] })
              void qc.invalidateQueries({ queryKey: ["reader-notes"] })
            })
          })
          .catch(() => {
            setGeneratedTitle(
              stripMarkdown(note.content).split("\n").find((l) => l.trim()) ?? "Untitled Note"
            )
            setIsGeneratingTitle(false)
          })
      } else {
        setGeneratedTitle(
          stripMarkdown(note.content).split("\n").find((l) => l.trim()) ?? "Untitled Note"
        )
      }
    }
  }, [note?.id, note?.content, note?.title, isNew])

  // Trigger tag suggestions on mode change or content threshold
  useEffect(() => {
    // If we're in edit mode, or if a newly saved note just switched to read mode
    const hasEnoughContent = editContent.trim().length > 30
    const needsTags = !isNew && note && note.tags.length === 0

    if (needsTags && hasEnoughContent && suggestedTags.length === 0 && !isFetchingTags) {
      void handleFetchSuggestions(mode === "edit")
    }
  }, [mode, isNew, note?.id, editContent.length])

  async function handleFetchSuggestions(autoAdd = false, injectedNote?: Note) {
    const targetNote = injectedNote || note
    if (!targetNote && !isNew) return
    // Tag suggestions for brand new notes aren't supported yet 
    if (!targetNote) return 

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setIsFetchingTags(true)
    try {
      const suggestions = await fetchSuggestedTags(targetNote.id, controller.signal)
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

  async function handleAddSuggestedTag(tag: string) {
    const newTags = [...new Set([...editTags, tag])]
    setEditTags(newTags)
    setSuggestedTags((prev) => prev.filter((t) => t !== tag))
    
    // If in read mode, we need to save this change immediately
    if (mode === "read" && note) {
      try {
        await patchNote(note.id, { tags: newTags })
        void qc.invalidateQueries({ queryKey: ["notes"] })
      } catch {
        // revert local state on error
        setEditTags(editTags)
      }
    }
  }

  const { data: collectionTree, isLoading: collectionsLoading } = useQuery({
    queryKey: ["collections-tree"],
    queryFn: () => fetchCollectionTree(),
    staleTime: 30_000,
    enabled: note !== null || isNew,
  })
  const allCollections = collectionTree ? flattenCollectionTree(collectionTree) : []

  const saveMut = useMutation({
    mutationFn: async () => {
      if (appendTarget) {
        return patchNote(appendTarget.id, {
          content: editContent,
          tags: editTags,
        })
      }
      if (isNew) {
        const saved = await createNote({
          content: editContent,
          tags: editTags,
          document_id: selectedDocIds[0] || null,
          source_document_ids: selectedDocIds,
        })
        // Apply any collection selections the user made while the note was
        // unsaved. Includes lockedCollectionId for back-compat -- if the
        // caller set both lockedCollectionId and added it to the staged set
        // (e.g. via initialCollectionId), the Set dedupes.
        const pending = new Set(checkedCollectionIds)
        if (lockedCollectionId) pending.add(lockedCollectionId)
        await Promise.all(
          Array.from(pending).map((cid) => addNoteToCollection(cid, saved.id)),
        )
        return saved
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
      void qc.invalidateQueries({ queryKey: ["reader-notes"] })
      if (!isNew) {
        setMode("read")
      }
      
      if (savedNote.title) {
        setGeneratedTitle(savedNote.title)
        setIsGeneratingTitle(false)
      } else if (savedNote.content.trim().length > 20) {
        setIsGeneratingTitle(true)
        suggestNoteTitle(savedNote.content)
          .then((title) => {
            setGeneratedTitle(title)
            setIsGeneratingTitle(false)
            void patchNote(savedNote.id, { title }).then(() => {
              void qc.invalidateQueries({ queryKey: ["notes"] })
              void qc.invalidateQueries({ queryKey: ["reader-notes"] })
            })
          })
          .catch(() => {
            setIsGeneratingTitle(false)
          })
      }
      // Trigger suggestions fetch for new notes so they are ready when the user clicks 'Edit' 
      if (isNew && savedNote.content.trim().length > 30) {
        void handleFetchSuggestions(false, savedNote)
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

  useNoteSaveShortcut(() => saveMut.mutate(), mode === "edit")

  useEffect(() => {
    if (pickerOpen && existingNotes.length === 0 && !notesLoading) {
      setNotesLoading(true)
      apiGet<ExistingNoteSummary[]>("/notes")
        .then(setExistingNotes)
        .catch(() => setExistingNotes([]))
        .finally(() => setNotesLoading(false))
    }
  }, [pickerOpen, existingNotes.length, notesLoading])

  const filteredExistingNotes = useMemo(() => {
    if (!pickerFilter.trim()) return existingNotes
    const lower = pickerFilter.toLowerCase()
    return existingNotes.filter(
      (n) =>
        n.content.toLowerCase().includes(lower) ||
        n.tags.some((t) => t.toLowerCase().includes(lower)),
    )
  }, [existingNotes, pickerFilter])

  function pickAppendTarget(target: ExistingNoteSummary) {
    setAppendTarget(target)
    setPickerOpen(false)
    setPickerFilter("")
    const tail = initialContent ?? ""
    setEditContent(tail ? `${target.content}\n\n---\n\n${tail}` : target.content)
    setEditTags(target.tags ?? [])
  }

  function clearAppendTarget() {
    setAppendTarget(null)
    setEditContent(initialContent ?? "")
    setEditTags([])
  }

  function commitTitleEdit() {
    if (!note) {
      setTitleEditing(false)
      return
    }
    const next = titleDraft.trim()
    setTitleEditing(false)
    // No-op if value didn't change.
    if ((next || null) === (note.title || null)) return
    void patchNote(note.id, { title: next }).then(() => {
      // Reflect immediately; refetch in the parent list view too.
      setGeneratedTitle(next)
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["reader-notes"] })
    })
  }

  function handleCollectionToggle(collectionId: string, checked: boolean) {
    // For new notes we don't have an id yet, so stage the selection in local
    // state. saveMut applies the staged set as memberships after createNote.
    if (isNew || !note) {
      setCheckedCollectionIds((prev) => {
        const next = new Set(prev)
        if (checked) next.add(collectionId)
        else next.delete(collectionId)
        return next
      })
      return
    }
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
        className={
          wideMode
            ? "w-[90vw] max-w-none sm:max-w-none flex flex-col p-0 overflow-hidden transition-[width] duration-200"
            : "w-[58vw] max-w-4xl sm:max-w-4xl flex flex-col p-0 overflow-hidden transition-[width] duration-200"
        }
      >
        <SheetHeader className="px-6 pt-6 pb-4 border-b border-border shrink-0">
          <button
            onClick={() => setWideMode((v) => !v)}
            className="absolute left-3 top-3 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            title={wideMode ? "Minimize to default width" : "Expand to wide view"}
            aria-label={wideMode ? "Minimize note sheet" : "Expand note sheet"}
          >
            {wideMode ? <ChevronsRight size={14} /> : <ChevronsLeft size={14} />}
          </button>
          <SheetTitle className="text-xl font-semibold leading-tight pl-7 pr-8 truncate">
            {appendTarget ? (
              `Appending to: ${firstLine(appendTarget.content) || "Untitled"}`
            ) : isGeneratingTitle ? (
              "Generating Title..."
            ) : titleEditing && note ? (
              <input
                autoFocus
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault()
                    commitTitleEdit()
                  } else if (e.key === "Escape") {
                    setTitleEditing(false)
                    setTitleDraft("")
                  }
                }}
                onBlur={commitTitleEdit}
                className="w-full bg-transparent border-b border-primary/40 text-xl font-semibold leading-tight focus:outline-none focus:border-primary"
              />
            ) : (
              <button
                onClick={() => {
                  if (!note) return  // can only rename a saved note
                  setTitleDraft(note.title ?? generatedTitle ?? "")
                  setTitleEditing(true)
                }}
                className="text-left w-full truncate hover:text-primary/90"
                title={note ? "Click to rename" : undefined}
              >
                {generatedTitle || title}
              </button>
            )}
          </SheetTitle>
          {sourceDoc && !appendTarget && (
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
          {isNew && (
            <SheetDescription asChild>
              <div className="mt-1 flex flex-col gap-2">
                {appendTarget ? (
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      Append mode
                    </span>
                    <span className="flex-1 truncate rounded bg-primary/10 px-2 py-1 text-xs text-foreground">
                      {firstLine(appendTarget.content)}
                    </span>
                    <button
                      onClick={clearAppendTarget}
                      className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                      aria-label="Clear append target"
                      title="Clear append target — back to new note"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ) : pickerOpen ? (
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-2 rounded border border-border bg-background px-2 py-1.5">
                      <Search size={13} className="text-muted-foreground" />
                      <input
                        type="text"
                        autoFocus
                        value={pickerFilter}
                        onChange={(e) => setPickerFilter(e.target.value)}
                        placeholder="Search all notes..."
                        className="flex-1 bg-transparent text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
                      />
                      <button
                        onClick={() => {
                          setPickerOpen(false)
                          setPickerFilter("")
                        }}
                        className="text-[10px] text-muted-foreground hover:text-foreground"
                      >
                        cancel
                      </button>
                    </div>
                    <div className="flex max-h-56 flex-col gap-1 overflow-auto">
                      {notesLoading && (
                        <p className="py-2 text-xs text-muted-foreground">Loading notes...</p>
                      )}
                      {!notesLoading && filteredExistingNotes.length === 0 && (
                        <p className="py-2 text-xs text-muted-foreground">No matching notes.</p>
                      )}
                      {filteredExistingNotes.map((n) => (
                        <button
                          key={n.id}
                          type="button"
                          onClick={() => pickAppendTarget(n)}
                          className="w-full rounded-md border border-border px-3 py-2 text-left transition-colors hover:border-muted-foreground/30 hover:bg-muted/50"
                        >
                          <p className="truncate text-xs text-foreground">{firstLine(n.content)}</p>
                          <div className="mt-0.5 flex items-center gap-2">
                            <span className="text-[10px] text-muted-foreground">
                              {formatRelative(n.updated_at)}
                            </span>
                            {n.tags.slice(0, 3).map((t) => (
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
                ) : (
                  <button
                    onClick={() => setPickerOpen(true)}
                    className="w-fit text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                  >
                    Append to existing note →
                  </button>
                )}
              </div>
            </SheetDescription>
          )}
        </SheetHeader>

        <div className={`flex-1 ${mode === "read" && !isNew ? "overflow-auto" : "flex flex-col overflow-hidden min-h-0"}`}>
          <div className={`px-6 py-5 ${mode === "read" && !isNew ? "min-h-full flex flex-col" : "flex flex-col flex-1 min-h-0 gap-4"}`}>
            {mode === "read" && !isNew ? (
              <>
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
                <div className="mt-12 pt-8 border-t border-border space-y-6 pb-24">
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-2 text-muted-foreground">
                      <Tag size={12} />
                      <span className="text-[10px] font-bold uppercase tracking-wider">Tags</span>
                    </div>
                    <div className="flex flex-col gap-3">
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
                      {suggestedTags.length > 0 && (
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[10px] font-medium text-muted-foreground">Suggestions:</span>
                          {suggestedTags.map((tag) => (
                            <button
                              key={tag}
                              onClick={() => void handleAddSuggestedTag(tag)}
                              className="flex items-center gap-1 rounded-full border border-dashed border-primary/30 bg-primary/5 px-2 py-0.5 text-[11px] text-primary hover:bg-primary/10 transition-colors"
                            >
                              <Check size={9} />
                              {tag}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center gap-2 text-muted-foreground">
                        <LayoutGrid size={12} />
                        <span className="text-[10px] font-bold uppercase tracking-wider">Collections</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {note && note.collections.length > 0 ? (
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
                    </div>
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center gap-2 text-muted-foreground">
                        <FileText size={12} />
                        <span className="text-[10px] font-bold uppercase tracking-wider">Source Documents</span>
                      </div>
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
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <NoteEditor
                layout="splitter"
                content={editContent}
                onContentChange={setEditContent}
                tags={editTags}
                onTagsChange={setEditTags}
                selectedDocIds={selectedDocIds}
                onSelectedDocIdsChange={setSelectedDocIds}
                checkedCollectionIds={checkedCollectionIds}
                onCollectionToggle={handleCollectionToggle}
                documents={documents}
                collections={allCollections}
                isNew={isNew}
                lockedCollectionId={lockedCollectionId ?? null}
                collectionsLoading={collectionsLoading}
                showCollections={!appendTarget}
                showSourceDocs={!appendTarget}
                suggestedTags={suggestedTags}
                suggestionsBusy={isFetchingTags}
                onSuggestTags={() => void handleFetchSuggestions()}
                onAddSuggestedTag={(tag) => void handleAddSuggestedTag(tag)}
                onDismissSuggestions={() => setSuggestedTags([])}
              />
            )}
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
                {saveMut.isPending
                  ? "Saving..."
                  : appendTarget
                    ? "Append"
                    : isNew
                      ? "Create Note"
                      : "Save Changes"}
              </button>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
