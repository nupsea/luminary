/**
 * QuickNoteComposer -- compact capture sheet for new notes. Title optional,
 * autosaving body, append-to-existing command, and an "open full note"
 * escape hatch into /notes/:id. Metadata beyond tags lives on the full page.
 */

import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Check, ExternalLink, Loader2, Search, X } from "lucide-react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { NoteEditor } from "@/components/notes/NoteEditor"
import { type NoteLinkCompletionConfig } from "@/components/notes/noteLinkCompletion"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { apiGet } from "@/lib/apiClient"
import {
  EMPTY_DRAFT,
  NEW_NOTE_KEY,
  useNoteAutosave,
} from "@/lib/noteAutosave"
import { useNoteSaveShortcut } from "@/lib/noteEditorUtils"
import {
  addNoteToCollection,
  createNoteLink,
  deleteNote,
  fetchNoteAutocomplete,
  patchNote,
  type Note,
} from "@/lib/notesApi"

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

export interface QuickNoteComposerProps {
  open: boolean
  onClose: () => void
  onSaved: (note: Note) => void
  initialContent?: string
  initialCollectionId?: string
  initialSourceDocIds?: string[]
  lockedCollectionId?: string | null
  /** Reader section capture: stamped onto the created note. */
  documentId?: string
  sectionId?: string | null
}

export function QuickNoteComposer({
  open,
  onClose,
  onSaved,
  initialContent,
  initialCollectionId,
  initialSourceDocIds,
  lockedCollectionId,
  documentId,
  sectionId,
}: QuickNoteComposerProps) {
  const [editContent, setEditContent] = useState("")
  const [editTitle, setEditTitle] = useState("")
  const [draftId, setDraftId] = useState<string | null>(null)
  const [appendTarget, setAppendTarget] = useState<ExistingNoteSummary | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerFilter, setPickerFilter] = useState("")
  const [existingNotes, setExistingNotes] = useState<ExistingNoteSummary[]>([])
  const [notesLoading, setNotesLoading] = useState(false)
  const closingRef = useRef(false)
  const qc = useQueryClient()
  const navigate = useNavigate()

  useEffect(() => {
    if (!open) return
    setEditContent(initialContent ?? "")
    setEditTitle("")
    setDraftId(null)
    setAppendTarget(null)
    setPickerOpen(false)
    setPickerFilter("")
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  function handleDraftCreated(saved: Note) {
    setDraftId(saved.id)
    const pending = new Set<string>()
    if (initialCollectionId) pending.add(initialCollectionId)
    if (lockedCollectionId) pending.add(lockedCollectionId)
    for (const cid of pending) {
      void addNoteToCollection(cid, saved.id).catch(() => {})
    }
  }

  const { status: saveStatus, flush, savedNoteId } = useNoteAutosave({
    bindKey: open ? (appendTarget ? null : NEW_NOTE_KEY) : null,
    baseline: EMPTY_DRAFT,
    draft: {
      content: editContent,
      title: editTitle,
      tags: [],
      sourceDocIds: initialSourceDocIds ?? [],
    },
    enabled: open && !appendTarget,
    createExtras: { documentId: documentId ?? null, sectionId: sectionId ?? null },
    onCreated: handleDraftCreated,
  })

  const linkCompletion = useMemo<NoteLinkCompletionConfig>(
    () => ({
      fetchCandidates: fetchNoteAutocomplete,
      excludeId: () => draftId,
      onPick: (targetId) => {
        const sourceId = draftId ?? savedNoteId()
        if (!sourceId || sourceId === targetId) return
        void createNoteLink(sourceId, targetId, "see-also").catch(() => {})
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [draftId],
  )

  const appendMut = useMutation({
    mutationFn: () => patchNote(appendTarget!.id, { content: editContent }),
    onSuccess: (savedNote) => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["notes-groups"] })
      onSaved(savedNote)
      onClose()
    },
  })

  async function finalize(): Promise<Note | null | "stay"> {
    let saved: Note | null
    try {
      saved = await flush()
    } catch {
      toast.error("Could not save note -- it stays open until saving works")
      return "stay"
    }
    const id = savedNoteId() ?? draftId
    if (id && !editContent.trim()) {
      try {
        await deleteNote(id)
        toast.info("Empty note discarded")
      } catch {
        // orphaned empty draft is harmless
      }
      void qc.invalidateQueries({ queryKey: ["notes"] })
      return null
    }
    return saved
  }

  async function handleDismiss() {
    if (closingRef.current) return
    closingRef.current = true
    try {
      if (appendTarget) {
        onClose()
        return
      }
      const result = await finalize()
      if (result === "stay") return
      if (result) onSaved(result)
      onClose()
    } finally {
      closingRef.current = false
    }
  }

  async function handleOpenFullNote() {
    const result = await finalize()
    if (result === "stay") return
    if (!result) {
      onClose()
      return
    }
    onSaved(result)
    onClose()
    navigate(`/notes/${result.id}`, { state: { from: window.location.pathname } })
  }

  useNoteSaveShortcut(() => {
    if (appendTarget) appendMut.mutate()
    else void flush().catch(() => {})
  }, open)

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
    const tail = editContent.trim() || (initialContent ?? "")
    setEditContent(tail ? `${target.content}\n\n---\n\n${tail}` : target.content)
  }

  function clearAppendTarget() {
    setAppendTarget(null)
    setEditContent(initialContent ?? "")
  }

  return (
    <Sheet
      open={open}
      onOpenChange={(o) => {
        if (!o) void handleDismiss()
      }}
    >
      <SheetContent
        side="right"
        className="flex w-[640px] max-w-full flex-col overflow-hidden p-0 sm:max-w-full"
        onEscapeKeyDown={(e) => {
          if (document.querySelector(".cm-tooltip-autocomplete")) e.preventDefault()
        }}
      >
        <SheetHeader className="shrink-0 border-b border-border px-5 pt-5 pb-3">
          <SheetTitle className="sr-only">
            {appendTarget ? "Append to note" : "New note"}
          </SheetTitle>
          <input
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            placeholder={appendTarget ? "Appending to existing note" : "Untitled note"}
            disabled={!!appendTarget}
            className="w-full bg-transparent pr-8 text-lg font-semibold leading-tight text-foreground placeholder:font-normal placeholder:text-muted-foreground/60 focus:outline-none disabled:opacity-70"
          />
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
                  <div className="flex max-h-48 flex-col gap-1 overflow-auto">
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
        </SheetHeader>

        <div className="flex min-h-0 flex-1 flex-col px-5 py-4">
          <NoteEditor
            layout="editor"
            content={editContent}
            onContentChange={setEditContent}
            linkCompletion={appendTarget ? undefined : linkCompletion}
            autoFocus
          />
        </div>

        <div className="flex shrink-0 items-center gap-3 border-t border-border bg-background px-5 py-3">
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
          {appendTarget ? (
            <>
              <button
                onClick={onClose}
                className="rounded border border-border bg-background px-4 py-2 text-xs text-muted-foreground hover:bg-accent transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => appendMut.mutate()}
                disabled={!editContent.trim() || appendMut.isPending}
                className="rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
              >
                {appendMut.isPending ? "Saving..." : "Append"}
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => void handleOpenFullNote()}
                disabled={!editContent.trim()}
                className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50 transition-colors"
                title="Continue in the full note page (tags, collections, links)"
              >
                <ExternalLink size={12} />
                Open full note
              </button>
              <button
                onClick={() => void handleDismiss()}
                className="rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                Done
              </button>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
