/**
 * NoteReaderSheet -- always-live note editor panel. No read/edit mode split:
 * the note is directly editable, with an optional distraction-free reading
 * view and a collapsible properties rail (tags / collections / source docs).
 */

import { useEffect, useMemo, useRef, useState } from "react"
import {
  BookOpen,
  Check,
  Columns2,
  FileText,
  LayoutGrid,
  Loader2,
  PanelRight,
  PencilLine,
  Search,
  Tag,
  Trash2,
  Wand2,
  X,
} from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { NoteConceptChips } from "@/components/NoteConceptChips"
import { TagAutocomplete } from "@/components/TagAutocomplete"
import { NoteBacklinks } from "@/components/notes/NoteBacklinks"
import { NoteEditor } from "@/components/notes/NoteEditor"
import { setImageSizeInMarkdown } from "@/components/notes/markdownEditorCommands"
import { NoteCollectionsField } from "@/components/notes/NoteCollectionsField"
import { NoteSourceDocsField } from "@/components/notes/NoteSourceDocsField"
import { type NoteLinkCompletionConfig } from "@/components/notes/noteLinkCompletion"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { apiGet } from "@/lib/apiClient"
import { flattenCollectionTree } from "@/lib/collectionUtils"
import { API_BASE } from "@/lib/config"
import {
  EMPTY_DRAFT,
  NEW_NOTE_KEY,
  useNoteAutosave,
  type NoteDraft,
} from "@/lib/noteAutosave"
import { useNoteSaveShortcut } from "@/lib/noteEditorUtils"
import { dispatchTagNavigate } from "@/lib/noteNavigateUtils"
import {
  addNoteToCollection,
  createNoteLink,
  deleteNote,
  fetchCollectionTree,
  fetchNoteAutocomplete,
  fetchSuggestedTags,
  patchNote,
  removeNoteFromCollection,
  type Note,
} from "@/lib/notesApi"
import { useNoteEditorUi } from "@/store/noteEditorUi"

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
  /** Navigate to another note (backlinks / [[ links). Absent = links read-only. */
  onOpenNote?: (noteId: string) => void
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
  onOpenNote,
}: NoteReaderSheetProps) {
  const [readingView, setReadingView] = useState(false)
  const [editContent, setEditContent] = useState("")
  const [editTags, setEditTags] = useState<string[]>([])
  const [checkedCollectionIds, setCheckedCollectionIds] = useState<Set<string>>(new Set())
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [suggestedTags, setSuggestedTags] = useState<string[]>([])
  const [isFetchingTags, setIsFetchingTags] = useState(false)
  const [editTitle, setEditTitle] = useState("")
  // Row auto-created by autosave for a still-"new" composer; deleted on close
  // if the content ends up empty.
  const [draftId, setDraftId] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const prevNoteId = useRef<string | undefined>(undefined)
  const prevIsNew = useRef<boolean>(false)
  const closingRef = useRef(false)
  const qc = useQueryClient()

  const propsRailOpen = useNoteEditorUi((s) => s.propsRailOpen)
  const setPropsRailOpen = useNoteEditorUi((s) => s.setPropsRailOpen)
  const splitPreview = useNoteEditorUi((s) => s.splitPreview)
  const setSplitPreview = useNoteEditorUi((s) => s.setSplitPreview)

  const [appendTarget, setAppendTarget] = useState<ExistingNoteSummary | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerFilter, setPickerFilter] = useState("")
  const [existingNotes, setExistingNotes] = useState<ExistingNoteSummary[]>([])
  const [notesLoading, setNotesLoading] = useState(false)

  const isOpen = note !== null || isNew

  useEffect(() => {
    if (isNew) {
      setEditContent(initialContent ?? "")
      setEditTags([])
      setEditTitle("")
      setDraftId(null)
      setCheckedCollectionIds(initialCollectionId ? new Set([initialCollectionId]) : new Set())
      setSelectedDocIds(initialSourceDocIds ?? [])
      setReadingView(false)
      setConfirmDelete(false)
      setSuggestedTags([])
      setIsFetchingTags(false)
      setAppendTarget(null)
      setPickerOpen(false)
      setPickerFilter("")
      prevIsNew.current = true
    } else if (note) {
      setEditContent(note.content)
      setEditTags(note.tags ?? [])
      setEditTitle(note.title ?? "")
      setCheckedCollectionIds(new Set((note.collections ?? []).map((c) => c.id)))
      setSelectedDocIds(
        note.source_document_ids?.length > 0
          ? note.source_document_ids
          : note.document_id
            ? [note.document_id]
            : [],
      )
      setReadingView(false)
      setConfirmDelete(false)

      // Only clear suggestions if we're switching to a genuinely different existing note.
      // Crucially, if we just transitioned from isNew=true to an actual note,
      // we DON'T clear suggestions because they were likely just fetched by the save.
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

  // Surface tag suggestions once a tagless note has enough content.
  useEffect(() => {
    const hasEnoughContent = editContent.trim().length > 30
    const needsTags = !isNew && note && note.tags.length === 0

    if (needsTags && hasEnoughContent && suggestedTags.length === 0 && !isFetchingTags) {
      void handleFetchSuggestions()
    }
  }, [isNew, note?.id, editContent.length])

  // Mod-e flips between the live editor and the distraction-free reading view.
  useEffect(() => {
    if (!isOpen) return
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "e") {
        e.preventDefault()
        setReadingView((v) => !v)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [isOpen])

  async function handleFetchSuggestions(injectedNote?: Note) {
    const targetNote = injectedNote || note
    if (!targetNote) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setIsFetchingTags(true)
    try {
      const suggestions = await fetchSuggestedTags(targetNote.id, controller.signal)
      if (controller.signal.aborted) return
      const novel = suggestions.filter((t) => !editTags.includes(t))
      setSuggestedTags(novel)
    } finally {
      if (!controller.signal.aborted) setIsFetchingTags(false)
    }
  }

  function handleAddSuggestedTag(tag: string) {
    // Autosave persists the change; no direct PATCH needed.
    setEditTags((prev) => [...new Set([...prev, tag])])
    setSuggestedTags((prev) => prev.filter((t) => t !== tag))
  }

  const { data: collectionTree, isLoading: collectionsLoading } = useQuery({
    queryKey: ["collections-tree"],
    queryFn: () => fetchCollectionTree(),
    staleTime: 30_000,
    enabled: isOpen,
  })
  const allCollections = collectionTree ? flattenCollectionTree(collectionTree) : []

  const autosaveEnabled = isOpen && !appendTarget

  function invalidateNoteQueries() {
    void qc.invalidateQueries({ queryKey: ["notes"] })
    void qc.invalidateQueries({ queryKey: ["reader-notes"] })
    void qc.invalidateQueries({ queryKey: ["notes-groups"] })
  }

  // The backend summarises the note into `description` in the background, so
  // refetch once shortly after to surface it on the card without a manual
  // refresh. The card shows the content snippet until then.
  function scheduleDescriptionRefetch(saved: Note) {
    if (saved.content.trim().length < 40) return
    setTimeout(() => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["reader-notes"] })
    }, 6000)
  }

  // Apply collection selections staged while the note had no id yet. Includes
  // lockedCollectionId for back-compat -- the Set dedupes if the caller set
  // both it and initialCollectionId.
  function handleDraftCreated(saved: Note) {
    setDraftId(saved.id)
    const pending = new Set(checkedCollectionIds)
    if (lockedCollectionId) pending.add(lockedCollectionId)
    for (const cid of pending) {
      void addNoteToCollection(cid, saved.id).catch(() => {})
    }
  }

  const autosaveBaseline: NoteDraft =
    isNew || !note
      ? EMPTY_DRAFT
      : {
          content: note.content,
          title: note.title ?? "",
          tags: note.tags ?? [],
          sourceDocIds:
            note.source_document_ids?.length > 0
              ? note.source_document_ids
              : note.document_id
                ? [note.document_id]
                : [],
        }

  const { status: saveStatus, flush, savedNoteId } = useNoteAutosave({
    // Suspended (null) while an append target is picked; append stays an
    // explicit action because it rewrites another note's content.
    bindKey: isNew ? (appendTarget ? null : NEW_NOTE_KEY) : (note?.id ?? null),
    baseline: autosaveBaseline,
    draft: { content: editContent, title: editTitle, tags: editTags, sourceDocIds: selectedDocIds },
    enabled: autosaveEnabled,
    onCreated: handleDraftCreated,
  })

  const appendMut = useMutation({
    mutationFn: () =>
      patchNote(appendTarget!.id, {
        content: editContent,
        tags: editTags,
      }),
    onSuccess: (savedNote) => {
      invalidateNoteQueries()
      scheduleDescriptionRefetch(savedNote)
      onSaved(savedNote)
    },
  })

  // Sheet dismissal (Esc / overlay / X / Done) flushes instead of discarding.
  // The sheet is controlled, so it stays open until this resolves; a failed
  // save keeps it open with the content intact.
  async function handleSheetDismiss() {
    if (closingRef.current) return
    closingRef.current = true
    try {
      if (!autosaveEnabled) {
        onClose()
        return
      }
      let saved: Note | null
      try {
        saved = await flush()
      } catch {
        toast.error("Could not save note -- it stays open until saving works")
        return
      }
      const emptyDraftId = isNew ? (savedNoteId() ?? draftId) : null
      if (isNew && emptyDraftId && !editContent.trim()) {
        try {
          await deleteNote(emptyDraftId)
          toast.info("Empty note discarded")
        } catch {
          // orphaned empty draft; the list refetch below still hides nothing real
        }
        invalidateNoteQueries()
        onClose()
        return
      }
      if (isNew && saved) {
        scheduleDescriptionRefetch(saved)
        onSaved(saved)
      } else if (saved) {
        invalidateNoteQueries()
        scheduleDescriptionRefetch(saved)
      }
      onClose()
    } finally {
      closingRef.current = false
    }
  }

  const deleteMut = useMutation({
    mutationFn: () => deleteNote(note!.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["notes-groups"] })
      onClose()
    },
  })

  // Flush pending edits before swapping to a linked note, so following a
  // link can never drop the current draft.
  async function handleOpenLinkedNote(targetId: string) {
    if (!onOpenNote) return
    try {
      await flush()
    } catch {
      toast.error("Could not save note before navigating")
      return
    }
    onOpenNote(targetId)
  }

  const linkCompletion = useMemo<NoteLinkCompletionConfig>(
    () => ({
      fetchCandidates: fetchNoteAutocomplete,
      excludeId: () => note?.id ?? draftId,
      onPick: (targetId) => {
        const sourceId = note?.id ?? draftId ?? savedNoteId()
        if (!sourceId || sourceId === targetId) return
        void createNoteLink(sourceId, targetId, "see-also")
          .then(() => {
            void qc.invalidateQueries({ queryKey: ["note-links", sourceId] })
          })
          .catch(() => {})
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [note?.id, draftId],
  )

  useNoteSaveShortcut(() => {
    if (appendTarget) appendMut.mutate()
    else void flush().catch(() => {})
  }, isOpen)

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

  function handleCollectionToggle(collectionId: string, checked: boolean) {
    // Before any row exists, stage the selection locally; handleDraftCreated
    // applies the staged set once autosave creates the note.
    const targetId = note?.id ?? draftId
    if (!targetId) {
      setCheckedCollectionIds((prev) => {
        const next = new Set(prev)
        if (checked) next.add(collectionId)
        else next.delete(collectionId)
        return next
      })
      return
    }
    if (checked) {
      void addNoteToCollection(collectionId, targetId).then(() => {
        setCheckedCollectionIds((prev) => new Set([...prev, collectionId]))
        void qc.invalidateQueries({ queryKey: ["notes"] })
      })
    } else {
      void removeNoteFromCollection(collectionId, targetId).then(() => {
        setCheckedCollectionIds((prev) => {
          const next = new Set(prev)
          next.delete(collectionId)
          return next
        })
        void qc.invalidateQueries({ queryKey: ["notes"] })
      })
    }
  }

  const displayTitle = appendTarget
    ? `Appending to: ${firstLine(appendTarget.content) || "Untitled"}`
    : editTitle.trim() || "Untitled note"

  const sourceDoc = !isNew && note?.document_id
    ? (documents.find((d) => d.id === note.document_id) ?? null)
    : null

  const tagChips = (
    <div className="flex flex-wrap gap-1.5">
      {editTags.length ? (
        editTags.map((t) => {
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
  )

  return (
    <Sheet
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) void handleSheetDismiss()
      }}
    >
      <SheetContent
        side="right"
        className="flex w-[90vw] max-w-none flex-col overflow-hidden p-0 sm:max-w-none"
      >
        <SheetHeader className="shrink-0 border-b border-border px-6 pt-6 pb-4">
          <div className="absolute left-3 top-3 flex items-center gap-1">
            <button
              onClick={() => setReadingView((v) => !v)}
              className={`rounded p-1 hover:bg-accent hover:text-foreground ${
                readingView ? "text-primary" : "text-muted-foreground"
              }`}
              title={readingView ? "Back to editor (Cmd+E)" : "Reading view (Cmd+E)"}
              aria-label={readingView ? "Back to editor" : "Reading view"}
            >
              {readingView ? <PencilLine size={14} /> : <BookOpen size={14} />}
            </button>
            {!readingView && (
              <>
                <button
                  onClick={() => setSplitPreview(!splitPreview)}
                  className={`rounded p-1 hover:bg-accent hover:text-foreground ${
                    splitPreview ? "text-primary" : "text-muted-foreground"
                  }`}
                  title={splitPreview ? "Hide preview pane" : "Show preview pane"}
                  aria-label={splitPreview ? "Hide preview pane" : "Show preview pane"}
                >
                  <Columns2 size={14} />
                </button>
                <button
                  onClick={() => setPropsRailOpen(!propsRailOpen)}
                  className={`rounded p-1 hover:bg-accent hover:text-foreground ${
                    propsRailOpen ? "text-primary" : "text-muted-foreground"
                  }`}
                  title={propsRailOpen ? "Hide properties" : "Show properties (tags, collections)"}
                  aria-label={propsRailOpen ? "Hide properties" : "Show properties"}
                >
                  <PanelRight size={14} />
                </button>
              </>
            )}
          </div>
          <SheetTitle className="text-xl font-semibold leading-tight pl-16 pr-8 truncate">
            {displayTitle}
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

        <div className="flex min-h-0 flex-1">
          {readingView ? (
            <div className="flex-1 overflow-auto">
              <div className="mx-auto max-w-3xl px-8 py-6">
                {editContent.trim() ? (
                  <MarkdownRenderer
                    serif
                    onNoteLinkClick={onOpenNote ? (id) => void handleOpenLinkedNote(id) : undefined}
                    onSetImageSize={(src, size) =>
                      setEditContent(setImageSizeInMarkdown(editContent, src, size, API_BASE))
                    }
                  >
                    {editContent}
                  </MarkdownRenderer>
                ) : (
                  <p className="text-muted-foreground italic text-sm">Start writing...</p>
                )}
                <div className="mt-12 space-y-6 border-t border-border pt-6 pb-12">
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-2 text-muted-foreground">
                      <Tag size={12} />
                      <span className="text-[10px] font-bold uppercase tracking-wider">Tags</span>
                    </div>
                    {tagChips}
                  </div>
                  {note?.id && !isNew && (
                    <NoteConceptChips noteId={note.id} noteTitle={note.title ?? undefined} />
                  )}
                  {note?.id && !isNew && (
                    <NoteBacklinks
                      noteId={note.id}
                      onOpenNote={onOpenNote ? (id) => void handleOpenLinkedNote(id) : undefined}
                    />
                  )}
                </div>
              </div>
            </div>
          ) : (
            <>
              <div className="flex min-h-0 flex-1 flex-col gap-3 px-6 py-5">
                {!appendTarget && (
                  <input
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    placeholder="Note title (optional)"
                    className="w-full shrink-0 bg-transparent text-lg font-semibold leading-tight text-foreground placeholder:text-muted-foreground/60 placeholder:font-normal focus:outline-none"
                  />
                )}
                <NoteEditor
                  layout={splitPreview ? "splitter" : "editor"}
                  content={editContent}
                  onContentChange={setEditContent}
                  linkCompletion={linkCompletion}
                />
                {note?.id && !isNew && !appendTarget && (
                  <NoteBacklinks
                    noteId={note.id}
                    onOpenNote={onOpenNote ? (id) => void handleOpenLinkedNote(id) : undefined}
                  />
                )}
              </div>

              {propsRailOpen && (
                <aside className="flex w-[320px] shrink-0 flex-col gap-5 overflow-hidden border-l border-border px-4 py-5">
                  <div className="flex max-h-[30%] shrink-0 flex-col gap-2 overflow-y-auto">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 text-muted-foreground">
                        <Tag size={12} />
                        <span className="text-[10px] font-bold uppercase tracking-wider">Tags</span>
                      </div>
                      {!isNew && note && (
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
                    <TagAutocomplete tags={editTags} onChange={setEditTags} />
                    {suggestedTags.length > 0 && (
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[10px] font-medium text-muted-foreground">
                          Suggestions:
                        </span>
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

                  {note?.id && !isNew && (
                    <div className="shrink-0">
                      <NoteConceptChips noteId={note.id} noteTitle={note.title ?? undefined} />
                    </div>
                  )}

                  {!appendTarget && (
                    <>
                      {/* Collections and source docs split the remaining rail
                          height instead of capping at tiny scroll boxes. */}
                      <div className="flex min-h-0 flex-1 flex-col gap-2">
                        <div className="flex shrink-0 items-center gap-2 text-muted-foreground">
                          <LayoutGrid size={12} />
                          <span className="text-[10px] font-bold uppercase tracking-wider">
                            Collections
                          </span>
                        </div>
                        <NoteCollectionsField
                          collections={allCollections}
                          checkedIds={checkedCollectionIds}
                          onToggle={handleCollectionToggle}
                          loading={collectionsLoading}
                          lockedCollectionId={lockedCollectionId ?? null}
                          className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto"
                        />
                      </div>
                      <div className="flex min-h-0 flex-1 flex-col gap-2">
                        <div className="flex shrink-0 items-center gap-2 text-muted-foreground">
                          <FileText size={12} />
                          <span className="text-[10px] font-bold uppercase tracking-wider">
                            Source Documents
                          </span>
                        </div>
                        <NoteSourceDocsField
                          documents={documents}
                          selectedIds={selectedDocIds}
                          onChange={setSelectedDocIds}
                          emptyMessage="No source documents available"
                          className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto"
                        />
                      </div>
                    </>
                  )}
                </aside>
              )}
            </>
          )}
        </div>

        <div className="shrink-0 border-t border-border bg-background px-6 py-4 flex items-center gap-3">
          {confirmDelete ? (
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
              <div
                role="status"
                className="mr-auto flex items-center gap-2 text-[10px] text-muted-foreground"
              >
                {appendTarget ? (
                  <>
                    <kbd className="rounded border bg-muted px-1">Ctrl+S</kbd> to save
                  </>
                ) : saveStatus === "saving" ? (
                  <>
                    <Loader2 size={12} className="animate-spin" />
                    Saving...
                  </>
                ) : saveStatus === "saved" ? (
                  <>
                    <Check size={12} className="text-green-600" />
                    Saved
                  </>
                ) : saveStatus === "error" ? (
                  <>
                    <span className="font-medium text-destructive">Save failed</span>
                    <button
                      onClick={() => void flush().catch(() => {})}
                      className="rounded border border-border px-2 py-0.5 hover:bg-accent"
                    >
                      Retry
                    </button>
                  </>
                ) : (
                  <>Autosaves as you type</>
                )}
              </div>
              {note && !isNew && (
                <button
                  onClick={() => setConfirmDelete(true)}
                  className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground hover:text-destructive hover:border-destructive transition-colors"
                  title="Delete Note"
                >
                  <Trash2 size={14} />
                </button>
              )}
              {appendTarget ? (
                <>
                  <button
                    onClick={onClose}
                    className="rounded border border-border bg-background px-4 py-2 text-xs text-muted-foreground hover:bg-accent shadow-sm transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => appendMut.mutate()}
                    disabled={!editContent.trim() || appendMut.isPending}
                    className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 shadow-sm transition-colors"
                  >
                    {appendMut.isPending ? "Saving..." : "Append"}
                  </button>
                </>
              ) : (
                <button
                  onClick={() => void handleSheetDismiss()}
                  className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 shadow-sm transition-colors"
                >
                  Done
                </button>
              )}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
