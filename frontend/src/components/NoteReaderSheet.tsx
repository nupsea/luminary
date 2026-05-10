/**
 * NoteReaderSheet -- full-width reader/editor panel for notes.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import { Check, FileText, GitBranch, LayoutGrid, Loader2, Maximize2, Minimize2, Pencil, Shapes, Tag, Trash2, Wand2 } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { NoteDiagramDialog } from "@/components/NoteDiagramDialog"
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
import { MERMAID_CHEAT_SHEET, MERMAID_TEMPLATES } from "@/lib/mermaidNotes"
import { uploadNoteAsset } from "@/lib/noteAssets"
import {
  replaceExcalidrawDiagram,
  type ExcalidrawNoteDiagramRef,
} from "@/lib/noteDiagrams"

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
  onSaved: (note: Note) => void
  isNew?: boolean
  initialContent?: string
  initialCollectionId?: string
  /** When set, this collection appears checked and cannot be unchecked (reader context). */
  lockedCollectionId?: string | null
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
  initialContent,
  initialCollectionId,
  lockedCollectionId,
}: NoteReaderSheetProps) {
  const [mode, setMode] = useState<"read" | "edit">(isNew ? "edit" : "read")
  const [editContent, setEditContent] = useState("")
  const [editTags, setEditTags] = useState<string[]>([])
  const [checkedCollectionIds, setCheckedCollectionIds] = useState<Set<string>>(new Set())
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [suggestedTags, setSuggestedTags] = useState<string[]>([])
  const [isFetchingTags, setIsFetchingTags] = useState(false)
  const [generatedTitle, setGeneratedTitle] = useState("")
  const [isGeneratingTitle, setIsGeneratingTitle] = useState(false)
  const [diagramOpen, setDiagramOpen] = useState(false)
  const [editingDiagramRef, setEditingDiagramRef] = useState<ExcalidrawNoteDiagramRef | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const previewRef = useRef<HTMLDivElement>(null)
  const splitContainerRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const prevNoteId = useRef<string | undefined>(undefined)
  const prevIsNew = useRef<boolean>(false)
  const qc = useQueryClient()
  // Resizable splitter / fullscreen / scroll sync
  const [leftPct, setLeftPct] = useState(50)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  // Echo guard: when we set scrollTop programmatically, the receiving pane
  // fires onScroll. syncingRef holds the source of the in-flight scroll until
  // the next animation frame so the echo is ignored.
  const syncingRef = useRef<"write" | "preview" | null>(null)

  function handleSplitterMouseDown(e: React.MouseEvent) {
    e.preventDefault()
    setIsDragging(true)
  }

  useEffect(() => {
    if (!isDragging) return
    function onMove(e: MouseEvent) {
      const el = splitContainerRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      const pct = ((e.clientX - rect.left) / rect.width) * 100
      setLeftPct(Math.min(85, Math.max(15, pct)))
    }
    function onUp() {
      setIsDragging(false)
    }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup", onUp)
    return () => {
      window.removeEventListener("mousemove", onMove)
      window.removeEventListener("mouseup", onUp)
    }
  }, [isDragging])

  function syncScroll(source: "write" | "preview") {
    if (syncingRef.current && syncingRef.current !== source) return
    const src = source === "write" ? textareaRef.current : previewRef.current
    const dst = source === "write" ? previewRef.current : textareaRef.current
    if (!src || !dst) return
    const srcMax = src.scrollHeight - src.clientHeight
    const dstMax = dst.scrollHeight - dst.clientHeight
    if (srcMax <= 0 || dstMax <= 0) return
    syncingRef.current = source
    dst.scrollTop = (src.scrollTop / srcMax) * dstMax
    requestAnimationFrame(() => {
      syncingRef.current = null
    })
  }

  function syncCaret() {
    const ta = textareaRef.current
    const dst = previewRef.current
    if (!ta || !dst) return

    // Stick to bottom if cursor is at the end of the document
    if (ta.selectionStart >= ta.value.length - 1) {
      dst.scrollTop = dst.scrollHeight
      return
    }

    const textBeforeCaret = ta.value.substring(0, ta.selectionStart)
    const linesBefore = textBeforeCaret.split("\n").length
    const totalLines = Math.max(1, ta.value.split("\n").length)
    
    const pct = linesBefore / totalLines
    const dstMax = dst.scrollHeight - dst.clientHeight
    if (dstMax > 0) {
      dst.scrollTop = pct * dstMax
    }
  }



  const adjustHeight = useCallback(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = "auto"
    ta.style.height = `${ta.scrollHeight}px`
  }, [])

  // Re-initialise local state when note changes or isNew changes
  useEffect(() => {
    if (isNew) {
      setEditContent(initialContent ?? "")
      setEditTags([])
      setCheckedCollectionIds(initialCollectionId ? new Set([initialCollectionId]) : new Set())
      setSelectedDocIds([])
      setMode("edit")
      setConfirmDelete(false)
      setSuggestedTags([])
      setIsFetchingTags(false)
      prevIsNew.current = true
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

  useEffect(() => {
    if (mode === "edit") {
      const timer = setTimeout(() => {
        syncCaret()
      }, 100)
      return () => clearTimeout(timer)
    }
  }, [editContent, mode])

  // Fetch LLM-generated title
  useEffect(() => {
    if (isNew) {
      setGeneratedTitle("New Note")
    } else if (note && note.content) {
      if (note.content.trim().length > 20) {
        setIsGeneratingTitle(true)
        fetch(`${API_BASE}/notes/suggest-title`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: note.content }),
        })
          .then((res) => res.json())
          .then((data: { title: string }) => {
            setGeneratedTitle(data.title)
            setIsGeneratingTitle(false)
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
  }, [note?.id, note?.content])

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

  // Focus textarea on entering edit mode. (Auto-grow disabled; the editor pane
  // now has a fixed height with its own internal scroll.)
  useEffect(() => {
    if (mode === "edit" && textareaRef.current) {
      // Clear any leftover inline height set by a previous adjustHeight call.
      textareaRef.current.style.height = ""
      textareaRef.current.focus()
    }
  }, [mode])
  // Silence unused-var lint: adjustHeight retained for future use but no longer wired.
  void adjustHeight

  // Ctrl+S / Cmd+S saves in edit mode. Guard against rapid repeats via a ref:
  // if a save is already in flight we drop the keystroke -- without this,
  // three Cmd+S taps before onSuccess fires would each call mutate() with
  // isNew still true, and the backend's 5-second hash dedup window can lose
  // the race when its auto-tagging step takes longer than the inter-press
  // gap. We use a ref instead of `[saveMut]` in deps because saveMut is
  // declared further down (TDZ) and because we don't want to rebind the
  // listener on every keystroke.
  const saveInFlightRef = useRef(false)
  useEffect(() => {
    if (mode !== "edit") return
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault()
        if (saveInFlightRef.current) return
        saveMut.mutate()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [mode]) // eslint-disable-line react-hooks/exhaustive-deps

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
      saveInFlightRef.current = true
      try {
        if (isNew) {
          const saved = await createNote({
            content: editContent,
            tags: editTags,
            document_id: selectedDocIds[0] || null,
            source_document_ids: selectedDocIds,
          })
          // When opened from the reader panel, auto-add to the book's collection
          if (lockedCollectionId) {
            await addNoteToCollection(lockedCollectionId, saved.id)
          }
          return saved
        } else {
          return patchNote(note!.id, {
            content: editContent,
            tags: editTags,
            source_document_ids: selectedDocIds,
          })
        }
      } finally {
        saveInFlightRef.current = false
      }
    },
    onSuccess: (savedNote) => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["reader-notes"] })
      if (!isNew) {
        setMode("read")
      }
      
      if (savedNote.content.trim().length > 20) {
        setIsGeneratingTitle(true)
        fetch(`${API_BASE}/notes/suggest-title`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: savedNote.content }),
        })
          .then((res) => res.json())
          .then((data: { title: string }) => {
            setGeneratedTitle(data.title)
            setIsGeneratingTitle(false)
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

  function insertAtCursor(markdown: string) {
    const start = textareaRef.current?.selectionStart ?? editContent.length
    const end = textareaRef.current?.selectionEnd ?? editContent.length
    const prefix = start > 0 && !editContent.slice(0, start).endsWith("\n") ? "\n\n" : ""
    const suffix = editContent.slice(end).startsWith("\n") ? "" : "\n\n"
    const insertion = `${prefix}${markdown}${suffix}`
    const next = editContent.substring(0, start) + insertion + editContent.substring(end)
    setEditContent(next)
    setTimeout(() => {
      const newPos = start + insertion.length
      textareaRef.current?.setSelectionRange(newPos, newPos)
      textareaRef.current?.focus()
    }, 0)
  }

  function handleDiagramSaved(markdown: string) {
    if (editingDiagramRef) {
      setEditContent((current) => replaceExcalidrawDiagram(current, editingDiagramRef, markdown))
      setEditingDiagramRef(null)
      return
    }
    insertAtCursor(markdown)
  }

  function openDiagramEditor(ref: ExcalidrawNoteDiagramRef) {
    if (note && mode === "read") {
      setEditContent(note.content)
      setMode("edit")
    }
    setEditingDiagramRef(ref)
    setDiagramOpen(true)
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
          isFullscreen
            ? "w-screen max-w-none sm:max-w-none flex flex-col p-0 overflow-hidden"
            : "w-[85vw] max-w-5xl sm:max-w-6xl flex flex-col p-0 overflow-hidden"
        }
      >
        <SheetHeader className="px-6 pt-6 pb-4 border-b border-border shrink-0">
          <SheetTitle className="text-xl font-semibold leading-tight pr-8 truncate">
            {isGeneratingTitle ? "Generating Title..." : generatedTitle || title}
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

        <div className={`flex-1 ${mode === "read" && !isNew ? "overflow-auto" : "flex flex-col overflow-hidden min-h-0"}`}>
          <div className={`px-6 py-5 ${mode === "read" && !isNew ? "min-h-full flex flex-col" : "flex flex-col flex-1 min-h-0 gap-4"}`}>
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
                  <MarkdownRenderer onEditExcalidrawDiagram={openDiagramEditor}>
                    {note.content}
                  </MarkdownRenderer>
                ) : (
                  <p className="text-muted-foreground italic text-sm">Start writing...</p>
                )}
              </div>
            ) : (
              <div
                ref={splitContainerRef}
                className={`flex items-stretch flex-1 min-h-0 overflow-hidden ${isDragging ? "select-none cursor-col-resize" : ""}`}
              >
                <div className="flex flex-col gap-2 min-w-0 min-h-0 h-full" style={{ width: `${leftPct}%` }}>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Editor</span>
                    <div className="flex flex-wrap items-center justify-end gap-1.5">
                      <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                        <GitBranch size={10} />
                        Mermaid:
                      </span>
                      {MERMAID_TEMPLATES.map((template) => (
                        <button
                          key={template.label}
                          type="button"
                          onClick={() => insertAtCursor(template.markdown)}
                          className="rounded border border-border bg-background px-1.5 py-0.5 text-[10px] font-medium text-foreground hover:bg-accent"
                        >
                          {template.label}
                        </button>
                      ))}
                      <button
                        type="button"
                        onClick={() => {
                          setEditingDiagramRef(null)
                          setDiagramOpen(true)
                        }}
                        className="flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-[10px] font-medium text-foreground hover:bg-accent"
                      >
                        <Shapes size={10} />
                        Draw
                      </button>
                      <span className="text-[10px] text-muted-foreground">Image spec:</span>
                      {(["small", "medium", "large"] as const).map((size) => (
                        <button
                          key={size}
                          type="button"
                          onClick={() => {
                            const start = textareaRef.current?.selectionStart ?? editContent.length
                            const end = textareaRef.current?.selectionEnd ?? editContent.length
                            const selectedText = editContent.substring(start, end)
                            
                            // If an existing image markdown is selected, try to inject/replace the size
                            let newMarkdown = ""
                            const imgRegex = /!\[([^\]]*?)\]\((.*?)\)/
                            const match = selectedText.match(imgRegex)
                            
                            if (match) {
                              const altText = match[1]
                              const url = match[2]
                              const altClean = altText.split("|")[0].trim() || "Image"
                              newMarkdown = `![${altClean}|${size}](${url})`
                            } else {
                              newMarkdown = `![Image|${size}](url)`
                            }

                            const newContent =
                              editContent.substring(0, start) +
                              newMarkdown +
                              editContent.substring(end)
                            setEditContent(newContent)
                            
                            setTimeout(() => {
                              const newPos = start + newMarkdown.length
                              textareaRef.current?.setSelectionRange(newPos, newPos)
                              textareaRef.current?.focus()
                            }, 0)
                          }}
                          className="rounded border border-border bg-background px-1.5 py-0.5 text-[10px] font-medium hover:bg-accent text-foreground capitalize"
                        >
                          {size}
                        </button>
                      ))}
                    </div>
                  </div>
                  <details className="rounded border border-border bg-muted/30 px-2 py-1 text-[11px] text-muted-foreground">
                    <summary className="cursor-pointer select-none font-medium text-foreground">Mermaid cheat sheet</summary>
                    <div className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
                      {MERMAID_CHEAT_SHEET.map((item) => (
                        <code key={item} className="rounded bg-background px-1.5 py-1 text-[10px] text-foreground">
                          {item}
                        </code>
                      ))}
                    </div>
                  </details>
                  <textarea
                    ref={textareaRef}
                    onScroll={() => syncScroll("write")}
                    value={editContent}
                    onPaste={async (e) => {
                      const items = e.clipboardData.items
                      for (let i = 0; i < items.length; i++) {
                        if (items[i].type.indexOf("image") !== -1) {
                          e.preventDefault()
                          const file = items[i].getAsFile()
                          if (!file) continue

                          try {
                            const data = await uploadNoteAsset(file)
                            const imgMarkdown = `![Pasted Image|medium](${data.path})`
                            const start = textareaRef.current?.selectionStart ?? editContent.length
                            const end = textareaRef.current?.selectionEnd ?? editContent.length
                            const newContent =
                              editContent.substring(0, start) +
                              imgMarkdown +
                              editContent.substring(end)

                            setEditContent(newContent)

                            // Restore focus and move cursor
                            setTimeout(() => {
                              const newPos = start + imgMarkdown.length
                              textareaRef.current?.setSelectionRange(newPos, newPos)
                              textareaRef.current?.focus()
                            }, 0)
                          } catch (err) {
                            console.error("Paste image failed", err)
                          }
                        }
                      }
                    }}
                    onChange={(e) => setEditContent(e.target.value)}
                    placeholder="Write your note in Markdown..."
                    className="w-full flex-1 resize-none overflow-auto rounded border-none bg-background px-2 py-2 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-0"
                  />
                </div>
                <div
                  onMouseDown={handleSplitterMouseDown}
                  className="mx-3 w-1 shrink-0 cursor-col-resize self-stretch rounded bg-border hover:bg-primary/40 transition-colors"
                  title="Drag to resize"
                />
                <div className="flex flex-col gap-2 min-w-0 min-h-0 h-full" style={{ width: `${100 - leftPct}%` }}>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Preview</span>
                  </div>
                  <div
                    ref={previewRef}
                    onScroll={() => syncScroll("preview")}
                    className="prose-sm flex-1 overflow-auto px-2 py-2"
                  >
                    {editContent.trim() ? (
                      <MarkdownRenderer onEditExcalidrawDiagram={openDiagramEditor}>
                        {editContent}
                      </MarkdownRenderer>
                    ) : (
                      <p className="text-muted-foreground italic text-sm">Preview will appear here...</p>
                    )}
                  </div>
                </div>
              </div>
            )}

            <div className={
              mode === "read" && !isNew
                ? "mt-12 pt-8 border-t border-border space-y-6 pb-24"
                : "shrink-0 pt-4 border-t border-border space-y-4 max-h-[30vh] overflow-y-auto pb-2"
            }>
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
                            className={`flex items-center gap-2 cursor-pointer rounded px-1 py-0.5 text-xs text-foreground hover:bg-accent/50 ${isNew || col.id === lockedCollectionId ? 'opacity-75' : ''}`}
                            title={col.id === lockedCollectionId ? "This collection is linked to the current document" : isNew ? "Create the note first to add to collections" : ""}
                          >
                            <input
                              type="checkbox"
                              checked={checkedCollectionIds.has(col.id) || col.id === lockedCollectionId}
                              onChange={(e) => handleCollectionToggle(col.id, e.target.checked)}
                              disabled={isNew || col.id === lockedCollectionId}
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
          <button
            onClick={() => setIsFullscreen((v) => !v)}
            className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-2 text-xs font-medium text-foreground hover:bg-accent shadow-sm transition-colors"
            title={isFullscreen ? "Exit fullscreen" : "Expand to full screen"}
          >
            {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            {isFullscreen ? "Collapse" : "Expand"}
          </button>
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

        <NoteDiagramDialog
          open={diagramOpen}
          onOpenChange={setDiagramOpen}
          scenePath={editingDiagramRef?.scenePath}
          onSaved={handleDiagramSaved}
        />
      </SheetContent>
    </Sheet>
  )
}
