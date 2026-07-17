/**
 * /notes/:noteId -- full-page note editor. Deep-linkable home for existing
 * notes: live CM6 editor, reading view, properties rail, backlinks, and an
 * outline rail for structured notes (3+ headings).
 */

import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import {
  ArrowLeft,
  BookOpen,
  Check,
  Columns2,
  Download,
  FileText,
  LayoutGrid,
  List,
  Loader2,
  PanelRight,
  PencilLine,
  Tag,
  Trash2,
  Wand2,
} from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { NoteConceptChips } from "@/components/NoteConceptChips"
import { TagAutocomplete } from "@/components/TagAutocomplete"
import { type MarkdownEditorHandle } from "@/components/notes/MarkdownCodeEditor"
import { NoteBacklinks } from "@/components/notes/NoteBacklinks"
import { NoteCollectionsField } from "@/components/notes/NoteCollectionsField"
import { NoteEditor } from "@/components/notes/NoteEditor"
import { NotePdfExport } from "@/components/notes/NotePdfExport"
import { NoteSourceDocsField } from "@/components/notes/NoteSourceDocsField"
import { setImageSizeInMarkdown } from "@/components/notes/markdownEditorCommands"
import { type NoteLinkCompletionConfig } from "@/components/notes/noteLinkCompletion"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet } from "@/lib/apiClient"
import { flattenCollectionTree } from "@/lib/collectionUtils"
import { API_BASE } from "@/lib/config"
import { EMPTY_DRAFT, useNoteAutosave, type NoteDraft } from "@/lib/noteAutosave"
import { downloadNoteMarkdown } from "@/lib/noteExport"
import { useNoteSaveShortcut } from "@/lib/noteEditorUtils"
import { dispatchTagNavigate } from "@/lib/noteNavigateUtils"
import {
  addNoteToCollection,
  createNoteLink,
  deleteNote,
  fetchCollectionTree,
  fetchNoteAutocomplete,
  fetchSuggestedTags,
  getNote,
  removeNoteFromCollection,
} from "@/lib/notesApi"
import { useBackNavigation } from "@/hooks/useBackNavigation"
import { useNoteEditorUi } from "@/store/noteEditorUi"

interface DocumentItem {
  id: string
  title: string
}

interface OutlineItem {
  level: number
  text: string
  line: number
  headingIndex: number
}

function parseOutline(content: string): OutlineItem[] {
  const items: OutlineItem[] = []
  let inFence = false
  content.split("\n").forEach((raw, line) => {
    if (/^\s*(```|~~~)/.test(raw)) inFence = !inFence
    if (inFence) return
    const m = raw.match(/^(#{1,3})\s+(.+)$/)
    if (m) {
      items.push({
        level: m[1].length,
        text: m[2].replace(/[`*_[\]]/g, "").trim(),
        line,
        headingIndex: items.length,
      })
    }
  })
  return items
}

export default function NotePage() {
  const { noteId } = useParams<{ noteId: string }>()
  const navigate = useNavigate()
  const { canGoBack, backLabel, goBack } = useBackNavigation()
  const qc = useQueryClient()

  const [readingView, setReadingView] = useState(false)
  const [editContent, setEditContent] = useState("")
  const [editTags, setEditTags] = useState<string[]>([])
  const [editTitle, setEditTitle] = useState("")
  const [checkedCollectionIds, setCheckedCollectionIds] = useState<Set<string>>(new Set())
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [exportMenuOpen, setExportMenuOpen] = useState(false)
  const [pdfExporting, setPdfExporting] = useState(false)
  const [suggestedTags, setSuggestedTags] = useState<string[]>([])
  const [isFetchingTags, setIsFetchingTags] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const editorHandleRef = useRef<MarkdownEditorHandle | null>(null)
  const proseRef = useRef<HTMLDivElement>(null)

  const propsRailOpen = useNoteEditorUi((s) => s.propsRailOpen)
  const setPropsRailOpen = useNoteEditorUi((s) => s.setPropsRailOpen)
  const splitPreview = useNoteEditorUi((s) => s.splitPreview)
  const setSplitPreview = useNoteEditorUi((s) => s.setSplitPreview)

  const {
    data: note,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["note", noteId],
    queryFn: () => getNote(noteId!),
    enabled: Boolean(noteId),
    retry: false,
    staleTime: 10_000,
  })

  const { data: documents = [] } = useQuery({
    queryKey: ["notes-documents"],
    queryFn: async () => {
      const data = await apiGet<{ items?: DocumentItem[] } | DocumentItem[]>("/documents", {
        page_size: "100",
      }).catch(() => [] as DocumentItem[])
      return Array.isArray(data) ? data : (data.items ?? [])
    },
    staleTime: 60_000,
  })

  const { data: collectionTree, isLoading: collectionsLoading } = useQuery({
    queryKey: ["collections-tree"],
    queryFn: () => fetchCollectionTree(),
    staleTime: 30_000,
  })
  const allCollections = collectionTree ? flattenCollectionTree(collectionTree) : []

  useEffect(() => {
    if (!note) return
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
    setSuggestedTags([])
    setIsFetchingTags(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [note?.id])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "e") {
        e.preventDefault()
        setReadingView((v) => !v)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  // Refresh list surfaces once on leave; per-keystroke invalidation would
  // refetch the whole notes list for every autosave.
  useEffect(() => {
    return () => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["reader-notes"] })
      void qc.invalidateQueries({ queryKey: ["notes-groups"] })
    }
  }, [qc])

  const autosaveBaseline: NoteDraft = note
    ? {
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
    : EMPTY_DRAFT

  const { status: saveStatus, flush } = useNoteAutosave({
    bindKey: note?.id ?? null,
    baseline: autosaveBaseline,
    draft: { content: editContent, title: editTitle, tags: editTags, sourceDocIds: selectedDocIds },
    enabled: Boolean(note),
    onSaved: (saved) => {
      qc.setQueryData(["note", noteId], saved)
    },
  })

  useNoteSaveShortcut(() => void flush().catch(() => {}), Boolean(note))

  async function handleFetchSuggestions() {
    if (!note) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setIsFetchingTags(true)
    try {
      const suggestions = await fetchSuggestedTags(note.id, controller.signal)
      if (controller.signal.aborted) return
      setSuggestedTags(suggestions.filter((t) => !editTags.includes(t)))
    } finally {
      if (!controller.signal.aborted) setIsFetchingTags(false)
    }
  }

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

  async function handleOpenLinkedNote(targetId: string) {
    try {
      await flush()
    } catch {
      toast.error("Could not save note before navigating")
      return
    }
    navigate(`/notes/${targetId}`, { state: { from: "/notes" } })
  }

  const linkCompletion = useMemo<NoteLinkCompletionConfig>(
    () => ({
      fetchCandidates: fetchNoteAutocomplete,
      excludeId: () => note?.id ?? null,
      onPick: (targetId) => {
        if (!note || note.id === targetId) return
        void createNoteLink(note.id, targetId, "see-also")
          .then(() => {
            void qc.invalidateQueries({ queryKey: ["note-links", note.id] })
          })
          .catch(() => {})
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [note?.id],
  )

  async function handleExportMarkdown() {
    setExportMenuOpen(false)
    if (!note) return
    try {
      await flush()
    } catch {
      toast.error("Could not save note before exporting")
      return
    }
    await downloadNoteMarkdown(note.id)
  }

  const deleteMut = useMutation({
    mutationFn: () => deleteNote(note!.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["notes-groups"] })
      navigate("/notes")
    },
  })

  const outline = useMemo(() => parseOutline(editContent), [editContent])
  const showOutline = outline.length >= 3

  function handleOutlineClick(item: OutlineItem) {
    if (readingView) {
      const headings = proseRef.current?.querySelectorAll("h1, h2, h3")
      headings?.[item.headingIndex]?.scrollIntoView({ behavior: "smooth", block: "start" })
    } else {
      editorHandleRef.current?.scrollToLine(item.line)
    }
  }

  if (isLoading) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-4 p-8">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    )
  }

  if (isError || !note) {
    return (
      <div className="flex flex-col items-center gap-3 py-24 text-center">
        <FileText size={32} className="text-muted-foreground/50" />
        <p className="text-base font-medium text-foreground">Note not found</p>
        <p className="text-sm text-muted-foreground">
          It may have been deleted, or the link is stale.
        </p>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void refetch()}
            className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-accent"
          >
            Retry
          </button>
          <button
            onClick={() => navigate("/notes")}
            className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            Back to Notes
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header: back, view toggles, title, status, delete */}
      <div className="shrink-0 border-b border-border px-6 pt-4 pb-3">
        <div className="mb-2 flex items-center gap-2">
          <button
            onClick={() => (canGoBack ? goBack() : navigate("/notes"))}
            className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <ArrowLeft size={12} />
            {canGoBack ? backLabel : "Back to Notes"}
          </button>
          <div className="ml-2 flex items-center gap-1">
            <button
              onClick={() => setReadingView((v) => !v)}
              className={`rounded p-1 hover:bg-accent hover:text-foreground ${
                readingView ? "text-primary" : "text-muted-foreground"
              }`}
              title={readingView ? "Back to editor (Cmd+E)" : "Reading view (Cmd+E)"}
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
                >
                  <Columns2 size={14} />
                </button>
                <button
                  onClick={() => setPropsRailOpen(!propsRailOpen)}
                  className={`rounded p-1 hover:bg-accent hover:text-foreground ${
                    propsRailOpen ? "text-primary" : "text-muted-foreground"
                  }`}
                  title={propsRailOpen ? "Hide properties" : "Show properties"}
                >
                  <PanelRight size={14} />
                </button>
              </>
            )}
          </div>
          <div
            role="status"
            className="ml-auto flex items-center gap-2 text-[10px] text-muted-foreground"
          >
            {saveStatus === "saving" ? (
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
          <div className="relative">
            <button
              onClick={() => setExportMenuOpen((v) => !v)}
              disabled={pdfExporting}
              className={`rounded-md border border-border bg-background p-1.5 transition-colors hover:text-foreground disabled:opacity-50 ${
                exportMenuOpen ? "text-foreground" : "text-muted-foreground"
              }`}
              title="Export note"
            >
              {pdfExporting ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Download size={13} />
              )}
            </button>
            {exportMenuOpen && (
              <div
                className="absolute right-0 top-full z-50 mt-0.5 min-w-[150px] rounded border border-border bg-popover py-1 shadow-md"
                onMouseLeave={() => setExportMenuOpen(false)}
              >
                <button
                  type="button"
                  className="w-full px-3 py-1 text-left text-xs hover:bg-accent"
                  onClick={() => void handleExportMarkdown()}
                >
                  Markdown (.md)
                </button>
                <button
                  type="button"
                  className="w-full px-3 py-1 text-left text-xs hover:bg-accent"
                  onClick={() => {
                    setExportMenuOpen(false)
                    setPdfExporting(true)
                  }}
                >
                  PDF (print)
                </button>
              </div>
            )}
          </div>
          {confirmDelete ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Delete note forever?</span>
              <button
                onClick={() => deleteMut.mutate()}
                disabled={deleteMut.isPending}
                className="rounded bg-destructive px-2.5 py-1 text-xs font-medium text-white hover:bg-destructive/90 disabled:opacity-50"
              >
                Confirm
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="rounded border border-border px-2.5 py-1 text-xs hover:bg-accent"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmDelete(true)}
              className="rounded-md border border-border bg-background p-1.5 text-muted-foreground hover:border-destructive hover:text-destructive transition-colors"
              title="Delete Note"
            >
              <Trash2 size={13} />
            </button>
          )}
        </div>
        <input
          value={editTitle}
          onChange={(e) => setEditTitle(e.target.value)}
          placeholder="Untitled note"
          readOnly={readingView}
          className="w-full bg-transparent text-2xl font-semibold leading-tight text-foreground placeholder:font-normal placeholder:text-muted-foreground/60 focus:outline-none"
        />
      </div>

      <div className="flex min-h-0 flex-1">
        {showOutline && (
          <nav className="hidden w-56 shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-border px-3 py-4 lg:flex">
            <div className="mb-1 flex items-center gap-2 px-2 text-muted-foreground">
              <List size={12} />
              <span className="text-[10px] font-bold uppercase tracking-wider">Outline</span>
            </div>
            {outline.map((item) => (
              <button
                key={`${item.line}-${item.text}`}
                onClick={() => handleOutlineClick(item)}
                className="truncate rounded px-2 py-1 text-left text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
                style={{ paddingLeft: `${8 + (item.level - 1) * 12}px` }}
                title={item.text}
              >
                {item.text}
              </button>
            ))}
          </nav>
        )}

        {readingView ? (
          <div className="flex-1 overflow-auto">
            <div ref={proseRef} className="mx-auto max-w-3xl px-8 py-6">
              {editContent.trim() ? (
                <MarkdownRenderer
                  serif
                  onNoteLinkClick={(id) => void handleOpenLinkedNote(id)}
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
                  <div className="flex flex-wrap gap-1.5">
                    {editTags.length ? (
                      editTags.map((t) => {
                        const parts = t.split("/")
                        return (
                          <button
                            key={t}
                            onClick={() => {
                              navigate("/notes")
                              dispatchTagNavigate(t)
                            }}
                            className="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs hover:bg-accent transition-colors"
                          >
                            <span className="text-primary">{parts[0]}</span>
                            {parts.length > 1 && (
                              <span className="text-muted-foreground">
                                {"/" + parts.slice(1).join("/")}
                              </span>
                            )}
                          </button>
                        )
                      })
                    ) : (
                      <span className="text-xs text-muted-foreground italic">No tags</span>
                    )}
                  </div>
                </div>
                <NoteConceptChips noteId={note.id} noteTitle={note.title ?? undefined} />
                <NoteBacklinks
                  noteId={note.id}
                  onOpenNote={(id) => void handleOpenLinkedNote(id)}
                />
              </div>
            </div>
          </div>
        ) : (
          <>
            <div className="flex min-h-0 flex-1 flex-col gap-3 px-6 py-4">
              <NoteEditor
                layout={splitPreview ? "splitter" : "editor"}
                content={editContent}
                onContentChange={setEditContent}
                linkCompletion={linkCompletion}
                editorRef={editorHandleRef}
              />
              <NoteBacklinks
                noteId={note.id}
                onOpenNote={(id) => void handleOpenLinkedNote(id)}
              />
            </div>

            {propsRailOpen && (
              <aside className="flex w-[320px] shrink-0 flex-col gap-5 overflow-hidden border-l border-border px-4 py-5">
                <div className="flex max-h-[30%] shrink-0 flex-col gap-2 overflow-y-auto">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-muted-foreground">
                      <Tag size={12} />
                      <span className="text-[10px] font-bold uppercase tracking-wider">Tags</span>
                    </div>
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
                          onClick={() => {
                            setEditTags((prev) => [...new Set([...prev, tag])])
                            setSuggestedTags((prev) => prev.filter((t) => t !== tag))
                          }}
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

                <div className="shrink-0">
                  <NoteConceptChips noteId={note.id} noteTitle={note.title ?? undefined} />
                </div>

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
              </aside>
            )}
          </>
        )}
      </div>
      {pdfExporting && (
        <NotePdfExport
          title={editTitle.trim() || note.title || ""}
          content={editContent}
          onDone={() => setPdfExporting(false)}
        />
      )}
    </div>
  )
}
