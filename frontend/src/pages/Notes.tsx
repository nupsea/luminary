/**
 * /notes — standalone notes management page with two-column layout.
 *
 * Audit: 2026-02-26
 * (a) fetchNotes calls GET /notes with params: document_id, group, tag — matches backend ✓
 * (b) Backend accepts document_id, group, tag params ✓
 * (c) Backend uses `content` for note body (not `text` or `body`)
 * (d) POST /notes returns flat NoteResponse (id, document_id, content, tags, group_name, created_at, updated_at)
 * (e) No create form existed — added (textarea, optional tags, doc selector, Save → POST /notes)
 *
 * Fixes applied per S50:
 * - Loading: 3 Skeleton h-12 rows (was 6 h-28 grid)
 * - Empty: "No notes yet. Click + to create your first note." + visible + button
 * - Error: inline amber alert "Could not load notes" + Retry button (was red, no retry)
 * - Create form: textarea + comma-separated tags input + doc selector + Save
 * - Delete: inline "Delete this note? [Yes] [No]" confirmation (was immediate delete)
 * - Edit: uses PATCH /notes/{id} (was PUT)
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BookOpen, FileText, Loader2, Network, Pencil, Plus, Tag, Trash2, Wand2, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { CollectionTree } from "@/components/CollectionTree"
import { CreateCollectionDialog } from "@/components/CreateCollectionDialog"
import { TagTree } from "@/components/TagTree"
import { GapDetectDialog } from "@/components/GapDetectDialog"
import { OrganizationPlanDialog } from "@/components/OrganizationPlanDialog"
import { GenerateFlashcardsDialog } from "@/components/GenerateFlashcardsDialog"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { NoteReaderSheet } from "@/components/NoteReaderSheet"
import { useDebounce } from "@/hooks/useDebounce"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ViewToggle } from "@/components/library/ViewToggle"
import { logger } from "@/lib/logger"
import { dispatchTagNavigate } from "@/lib/noteNavigateUtils"
import { stripMarkdown } from "@/lib/utils"
import { formatDate, relativeDate } from "@/components/library/utils"
import { useAppStore } from "@/store"

import { API_BASE } from "@/lib/config"

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

interface GroupInfo { name: string; count: number }
interface TagInfo { name: string; count: number }
interface GroupsData { groups: GroupInfo[]; tags: TagInfo[]; total_notes: number }

interface DocumentItem {
  id: string
  title: string
}

interface Clip {
  id: string
  document_id: string
  section_id: string | null
  section_heading: string | null
  pdf_page_number: number | null
  selected_text: string
  user_note: string
  created_at: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchNotes(
  documentId?: string,
  group?: string,
  tag?: string,
  collectionId?: string,
): Promise<Note[]> {
  const params = new URLSearchParams()
  if (documentId) params.set("document_id", documentId)
  if (group) params.set("group", group)
  if (tag) params.set("tag", tag)
  if (collectionId) params.set("collection_id", collectionId)
  const res = await fetch(`${API_BASE}/notes?${params.toString()}`)
  if (!res.ok) throw new Error(`GET /notes failed: ${res.status}`)
  return res.json() as Promise<Note[]>
}

async function fetchGroups(): Promise<GroupsData> {
  const res = await fetch(`${API_BASE}/notes/groups`)
  if (!res.ok) return { groups: [], tags: [], total_notes: 0 }
  return res.json() as Promise<GroupsData>
}

async function fetchDocumentList(): Promise<DocumentItem[]> {
  const res = await fetch(`${API_BASE}/documents?page_size=200`)
  if (!res.ok) return []
  const data = (await res.json()) as { items?: DocumentItem[] } | DocumentItem[]
  return Array.isArray(data) ? data : (data.items ?? [])
}

async function deleteNote(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/notes/${id}`, { method: "DELETE" })
  if (!res.ok && res.status !== 204) throw new Error(`DELETE /notes/${id} failed: ${res.status}`)
}

async function fetchClips(documentId?: string): Promise<Clip[]> {
  const params = new URLSearchParams()
  if (documentId) params.set("document_id", documentId)
  const res = await fetch(`${API_BASE}/clips?${params.toString()}`)
  if (!res.ok) throw new Error(`GET /clips failed: ${res.status}`)
  return res.json() as Promise<Clip[]>
}

async function patchClipNote(id: string, userNote: string): Promise<Clip> {
  const res = await fetch(`${API_BASE}/clips/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_note: userNote }),
  })
  if (!res.ok) throw new Error(`PATCH /clips/${id} failed: ${res.status}`)
  return res.json() as Promise<Clip>
}

async function deleteClip(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/clips/${id}`, { method: "DELETE" })
  if (!res.ok && res.status !== 204) throw new Error(`DELETE /clips/${id} failed: ${res.status}`)
}

async function createNoteFromClip(clip: Clip, docTitle: string): Promise<{ id: string }> {
  const body = `> ${clip.selected_text}\n\n*Source: ${docTitle}${clip.section_heading ? ` — ${clip.section_heading}` : ""}*`
  const res = await fetch(`${API_BASE}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content: body,
      tags: ["clip"],
      document_id: clip.document_id,
      section_id: clip.section_id ?? null,
    }),
  })
  if (!res.ok) throw new Error(`POST /notes failed: ${res.status}`)
  return res.json() as Promise<{ id: string }>
}

// ---------------------------------------------------------------------------
// Cluster suggestion types + API helpers
// ---------------------------------------------------------------------------

interface ClusterNotePreview {
  note_id: string
  excerpt: string
}

interface ClusterSuggestion {
  id: string
  suggested_name: string
  note_ids: string[]
  note_count: number
  confidence_score: number
  status: string
  created_at: string
  previews: ClusterNotePreview[]
}

async function fetchClusterSuggestions(): Promise<ClusterSuggestion[]> {
  const res = await fetch(`${API_BASE}/notes/cluster/suggestions`)
  if (!res.ok) throw new Error(`GET /notes/cluster/suggestions failed: ${res.status}`)
  return res.json() as Promise<ClusterSuggestion[]>
}

async function postCluster(): Promise<{ queued?: boolean; cached?: boolean; total_notes?: number; last_run?: string }> {
  const res = await fetch(`${API_BASE}/notes/cluster`, { method: "POST" })
  if (!res.ok) throw new Error(`POST /notes/cluster failed: ${res.status}`)
  return res.json() as Promise<{ queued?: boolean; cached?: boolean; total_notes?: number; last_run?: string }>
}

// Individual accept/reject API helpers removed; OrganizationPlanDialog uses batch-accept.
// Backend endpoints preserved for backward compatibility.

interface NoteSearchItem {
  note_id: string
  content: string
  tags: string[]
  group_name: string | null
  document_id: string | null
  score: number
  source: string
}

interface NoteSearchResponse {
  query: string
  results: NoteSearchItem[]
  total: number
}

async function fetchNoteSearch(q: string, k = 10): Promise<NoteSearchResponse> {
  const params = new URLSearchParams({ q, k: String(k) })
  const res = await fetch(`${API_BASE}/notes/search?${params.toString()}`)
  if (!res.ok) throw new Error(`GET /notes/search failed: ${res.status}`)
  return res.json() as Promise<NoteSearchResponse>
}

// ---------------------------------------------------------------------------
// ClipCard — single clip entry in Reading Journal
// ---------------------------------------------------------------------------

interface ClipCardProps {
  clip: Clip
  docTitle: string
  onDeleted: () => void
  onConvertToNote: (clip: Clip) => void
  onCreateFlashcard: (clip: Clip) => void
  navigate: (url: string) => void
}

function ClipCard({ clip, docTitle, onDeleted, onConvertToNote, onCreateFlashcard, navigate }: ClipCardProps) {
  const [confirming, setConfirming] = useState(false)
  const [noteText, setNoteText] = useState(clip.user_note)
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle")
  const abortRef = useRef<AbortController | null>(null)
  const qc = useQueryClient()

  const deleteMut = useMutation({
    mutationFn: () => deleteClip(clip.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["clips"] })
      onDeleted()
    },
  })

  async function handleNoteBlur() {
    if (noteText === clip.user_note) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setSaveStatus("saving")
    try {
      await patchClipNote(clip.id, noteText)
      setSaveStatus("saved")
      void qc.invalidateQueries({ queryKey: ["clips"] })
      setTimeout(() => setSaveStatus("idle"), 2000)
    } catch {
      if (!controller.signal.aborted) setSaveStatus("error")
    }
  }

  const attribution = [
    docTitle,
    clip.section_heading,
  ]
    .filter(Boolean)
    .join(" — ")

  const sourceUrl = clip.section_id
    ? `/?doc=${clip.document_id}&section_id=${clip.section_id}`
    : clip.pdf_page_number
      ? `/?doc=${clip.document_id}&page=${clip.pdf_page_number}`
      : `/?doc=${clip.document_id}`

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3">
      {/* Blockquote */}
      <blockquote className="border-l-4 border-l-blue-400 pl-3 text-sm italic text-foreground">
        {clip.selected_text}
      </blockquote>

      {/* Attribution */}
      <p className="text-xs text-muted-foreground">{attribution}</p>

      {/* User note */}
      <div className="relative">
        <textarea
          value={noteText}
          onChange={(e) => setNoteText(e.target.value)}
          onBlur={() => void handleNoteBlur()}
          placeholder="Add your note..."
          className="w-full resize-none rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          rows={2}
        />
        {saveStatus === "saving" && (
          <span className="absolute bottom-1 right-2 text-xs text-muted-foreground">Saving...</span>
        )}
        {saveStatus === "saved" && (
          <span className="absolute bottom-1 right-2 text-xs text-green-600">Saved</span>
        )}
        {saveStatus === "error" && (
          <span className="absolute bottom-1 right-2 text-xs text-red-600">Save failed</span>
        )}
      </div>

      {/* Actions row */}
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <button
          onClick={() => navigate(sourceUrl)}
          className="rounded border border-border px-2 py-0.5 text-muted-foreground hover:text-foreground hover:bg-accent"
        >
          Navigate to source
        </button>
        <button
          onClick={() => onConvertToNote(clip)}
          className="rounded border border-border px-2 py-0.5 text-muted-foreground hover:text-foreground hover:bg-accent"
        >
          Convert to Note
        </button>
        <button
          onClick={() => onCreateFlashcard(clip)}
          className="rounded border border-border px-2 py-0.5 text-muted-foreground hover:text-foreground hover:bg-accent"
        >
          Create Flashcard
        </button>
        <div className="flex-1" />
        <span className="text-muted-foreground">{relativeDate(clip.created_at)}</span>
        {confirming ? (
          <>
            <button
              onClick={() => deleteMut.mutate()}
              disabled={deleteMut.isPending}
              className="rounded bg-destructive px-2 py-0.5 text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
            >
              Yes
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="rounded border border-border px-2 py-0.5 hover:bg-accent"
            >
              No
            </button>
          </>
        ) : (
          <button
            onClick={() => setConfirming(true)}
            className="rounded p-0.5 text-muted-foreground hover:text-destructive hover:bg-accent"
            title="Delete clip"
          >
            <Trash2 size={12} />
          </button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ReadingJournalTab
// ---------------------------------------------------------------------------

interface ReadingJournalTabProps {
  documents: DocumentItem[]
  onConvertToNote: (clip: Clip) => void
  onCreateFlashcard: (clip: Clip) => void
  navigate: (url: string) => void
}

function ReadingJournalTab({ documents, onConvertToNote, onCreateFlashcard, navigate }: ReadingJournalTabProps) {
  const [groupByDoc, setGroupByDoc] = useState(false)
  const qc = useQueryClient()

  const { data: clips, isLoading, isError, refetch } = useQuery({
    queryKey: ["clips"],
    queryFn: () => fetchClips(),
  })

  const docTitleMap = Object.fromEntries(documents.map((d) => [d.id, d.title]))

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full rounded-lg" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex items-center gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <span className="flex-1">Could not load clips</span>
        <button
          onClick={() => void refetch()}
          className="rounded border border-amber-300 bg-white px-3 py-1 text-xs text-amber-700 hover:bg-amber-50"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!clips || clips.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-20 text-center">
        <BookOpen size={32} className="text-muted-foreground/50" />
        <p className="text-base font-medium text-foreground">No clips yet</p>
        <p className="text-sm text-muted-foreground">
          Select text in the Document Reader and click &ldquo;Clip&rdquo; to save a passage.
        </p>
      </div>
    )
  }

  function handleDeleted() {
    void qc.invalidateQueries({ queryKey: ["clips"] })
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Toolbar */}
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={groupByDoc}
            onChange={(e) => setGroupByDoc(e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border"
          />
          Group by document
        </label>
        <span className="ml-auto text-xs text-muted-foreground">{clips.length} clip{clips.length !== 1 ? "s" : ""}</span>
      </div>

      {groupByDoc ? (
        // Grouped view — native <details>/<summary> (no shadcn Accordion)
        (() => {
          const grouped = clips.reduce<Record<string, Clip[]>>((acc, c) => {
            const key = c.document_id
            ;(acc[key] ??= []).push(c)
            return acc
          }, {})
          return Object.entries(grouped).map(([docId, docClips]) => (
            <details key={docId} open className="rounded-lg border border-border">
              <summary className="cursor-pointer rounded-t-lg bg-muted px-3 py-2 text-sm font-medium text-foreground select-none">
                {docTitleMap[docId] ?? docId}
                <span className="ml-2 text-xs font-normal text-muted-foreground">
                  {docClips.length} clip{docClips.length !== 1 ? "s" : ""}
                </span>
              </summary>
              <div className="flex flex-col gap-2 p-2">
                {docClips.map((clip) => (
                  <ClipCard
                    key={clip.id}
                    clip={clip}
                    docTitle={docTitleMap[clip.document_id] ?? clip.document_id}
                    onDeleted={handleDeleted}
                    onConvertToNote={onConvertToNote}
                    onCreateFlashcard={onCreateFlashcard}
                    navigate={navigate}
                  />
                ))}
              </div>
            </details>
          ))
        })()
      ) : (
        // Flat list — newest first
        clips.map((clip) => (
          <ClipCard
            key={clip.id}
            clip={clip}
            docTitle={docTitleMap[clip.document_id] ?? clip.document_id}
            onDeleted={handleDeleted}
            onConvertToNote={onConvertToNote}
            onCreateFlashcard={onCreateFlashcard}
            navigate={navigate}
          />
        ))
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// NoteCard — card view; editing is delegated to NoteEditorDialog
// ---------------------------------------------------------------------------

interface NoteCardProps {
  note: Note
  onEdit: () => void
  onDeleted: () => void
}

function NoteCard({ note, onEdit, onDeleted }: NoteCardProps) {
  const [confirming, setConfirming] = useState(false)
  const qc = useQueryClient()

  const deleteMut = useMutation({
    mutationFn: () => deleteNote(note.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["notes-groups"] })
      onDeleted()
    },
  })

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3">
      {/* Header row */}
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {note.document_id && <FileText size={12} />}
        <span className="flex-1 truncate">{relativeDate(note.updated_at)}</span>
        {note.group_name && (
          <span className="rounded-full bg-muted px-2 py-0.5">{note.group_name}</span>
        )}
        <button
          onClick={() => { onEdit(); setConfirming(false) }}
          className="hover:text-foreground"
          title="Edit"
        >
          <Pencil size={12} />
        </button>
        <button
          onClick={() => setConfirming((v) => !v)}
          className="hover:text-destructive"
          title="Delete"
        >
          <Trash2 size={12} />
        </button>
      </div>

      {/* Inline delete confirmation */}
      {confirming && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>Delete this note?</span>
          <button
            onClick={() => deleteMut.mutate()}
            disabled={deleteMut.isPending}
            className="rounded bg-destructive px-2 py-0.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
          >
            Yes
          </button>
          <button
            onClick={() => setConfirming(false)}
            className="rounded border border-border px-2 py-0.5 text-xs hover:bg-accent"
          >
            No
          </button>
        </div>
      )}

      {/* Content — click to open editor dialog */}
      {!confirming && (
        <div className="cursor-pointer" onClick={onEdit}>
          <MarkdownRenderer>{note.content.slice(0, 200)}</MarkdownRenderer>
        </div>
      )}

      {/* Tags -- breadcrumb style: root in text-primary, /child in text-muted-foreground */}
      {note.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {note.tags.map((t) => {
            const parts = t.split("/")
            return (
              <button
                key={t}
                onClick={(e) => { e.stopPropagation(); dispatchTagNavigate(t) }}
                className="flex items-center gap-0.5 rounded-full bg-muted px-2 py-0.5 text-xs hover:bg-accent transition-colors"
                title={`Filter by tag: ${t}`}
              >
                <Tag size={9} className="text-muted-foreground" />
                <span className="text-primary">{parts[0]}</span>
                {parts.length > 1 && (
                  <span className="text-muted-foreground">{"/" + parts.slice(1).join("/")}</span>
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

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
  const mountTime = useRef(Date.now())
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
    logger.info("[Notes] mounted")
  }, [])

  // S197: consume notePreload from store (set by gap analysis "Take a note" action)
  useEffect(() => {
    if (notePreload) {
      setIsCreating(true)
      // preload is consumed by NoteReaderSheet via props; clear store after opening
      // Use a microtask to ensure the sheet opens first
      queueMicrotask(() => setNotePreload(null))
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

  // S165: Fetch tree to resolve ID to name in header
  const { data: tree } = useQuery({
    queryKey: ["collections-tree"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/collections/tree`)
      return (await res.json()) as any[]
    },
    staleTime: 30_000,
  })

  const getCollectionName = (id: string) => {
    if (!tree) return id.slice(0, 8) + "..."
    const flat = (items: any[]): any[] => items.flatMap(i => [i, ...flat(i.children || [])])
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

  async function handleAutoOrganize() {
    setIsClusterQueued(true)
    try {
      const result = await postCluster()
      if (result.cached) {
        // Already have pending suggestions -- show the plan immediately
        setIsClusterQueued(false)
        setShowOrgPlan(true)
        return
      }
      // Poll suggestions after a short delay to give clustering a head start
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

  // Individual accept/reject kept as API helpers (backward compat) but UI uses OrganizationPlanDialog

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
  let panelContent: React.ReactNode

  if (filter.type === "journal") {
    panelContent = (
      <ReadingJournalTab
        documents={documents}
        onConvertToNote={(clip) => void handleConvertClipToNote(clip)}
        onCreateFlashcard={(clip) => void handleCreateFlashcardFromClip(clip)}
        navigate={navigate}
      />
    )
  } else if (isSearchMode) {
    if (searchLoading) {
      panelContent = (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      )
    } else if (searchError) {
      panelContent = (
        <div className="flex items-center gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <span className="flex-1">Search failed</span>
          <button
            onClick={() => void refetchSearch()}
            className="rounded border border-amber-300 bg-white px-3 py-1 text-xs text-amber-700 hover:bg-amber-50"
          >
            Retry
          </button>
        </div>
      )
    } else if (!searchData || searchData.results.length === 0) {
      panelContent = (
        <div className="flex flex-col items-center gap-3 py-20 text-center">
          <p className="text-sm text-muted-foreground">No notes matching &ldquo;{debouncedQuery}&rdquo;</p>
        </div>
      )
    } else {
      panelContent = (
        <div className="flex flex-col gap-3">
          {searchData.results.map((result) => {
            const matchedNote = noteList.find((n) => n.id === result.note_id)
            return (
              <div
                key={result.note_id}
                className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3 cursor-pointer hover:bg-accent/50"
                onClick={() => {
                  if (matchedNote) setEditingNote(matchedNote)
                }}
              >
                <div className="text-sm text-foreground line-clamp-3">
                  {stripMarkdown(result.content).slice(0, 150)}
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  {result.tags.map((t) => {
                    const parts = t.split("/")
                    return (
                      <button
                        key={t}
                        onClick={(e) => { e.stopPropagation(); dispatchTagNavigate(t) }}
                        className="flex items-center gap-0.5 rounded-full bg-muted px-2 py-0.5 text-xs hover:bg-accent transition-colors"
                        title={`Filter by tag: ${t}`}
                      >
                        <Tag size={9} className="text-muted-foreground" />
                        <span className="text-primary">{parts[0]}</span>
                        {parts.length > 1 && (
                          <span className="text-muted-foreground">{"/" + parts.slice(1).join("/")}</span>
                        )}
                      </button>
                    )
                  })}
                  <span className="ml-auto text-xs text-muted-foreground">
                    {result.source === "both" ? "FTS + Semantic" : result.source === "vector" ? "Semantic" : "FTS"}
                    {" · "}
                    {result.score.toFixed(4)}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )
    }
  } else if (notesLoading) {
    panelContent =
      notesView === "list" ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead>Tags</TableHead>
              <TableHead>Group</TableHead>
              <TableHead>Created At</TableHead>
              <TableHead>Document</TableHead>
              <TableHead>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Array.from({ length: 3 }).map((_, i) => (
              <TableRow key={i}>
                <TableCell><Skeleton className="h-4 w-40" /></TableCell>
                <TableCell><Skeleton className="h-4 w-20" /></TableCell>
                <TableCell><Skeleton className="h-4 w-16" /></TableCell>
                <TableCell><Skeleton className="h-4 w-24" /></TableCell>
                <TableCell><Skeleton className="h-4 w-24" /></TableCell>
                <TableCell><Skeleton className="h-4 w-8" /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Skeleton className="h-28 w-full rounded-lg" />
          <Skeleton className="h-28 w-full rounded-lg" />
        </div>
      )
  } else if (notesError) {
    panelContent = (
      <div className="flex items-center gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <span className="flex-1">Could not load notes</span>
        <button
          onClick={() => void refetch()}
          className="rounded border border-amber-300 bg-white px-3 py-1 text-xs text-amber-700 hover:bg-amber-50"
        >
          Retry
        </button>
      </div>
    )
  } else if (noteList.length === 0) {
    panelContent = activeTag ? (
      <div className="flex flex-col items-center gap-3 py-20 text-center">
        <Tag size={32} className="text-muted-foreground/50" />
        <p className="text-base font-medium text-foreground">
          No other notes tagged with {activeTag}
        </p>
        <p className="text-sm text-muted-foreground">
          Notes tagged with this tag will appear here.
        </p>
      </div>
    ) : (
      <div className="flex flex-col items-center gap-3 py-20 text-center">
        <Network size={32} className="text-muted-foreground/50" />
        <p className="text-base font-medium text-foreground">No notes yet</p>
        <p className="text-sm text-muted-foreground">Click + to create your first note.</p>
        <button
          onClick={() => setIsCreating(true)}
          className="flex items-center gap-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground hover:bg-accent"
        >
          <Plus size={14} />
          New note
        </button>
      </div>
    )
  } else if (notesView === "list") {
    // Build doc title lookup from already-fetched document list
    const docTitleMap = Object.fromEntries(documents.map((d) => [d.id, d.title]))

    panelContent = (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Title</TableHead>
            <TableHead>Tags</TableHead>
            <TableHead>Group</TableHead>
            <TableHead>Created At</TableHead>
            <TableHead>Document</TableHead>
            <TableHead>Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {noteList.map((note) => (
            <TableRow
              key={note.id}
              className="cursor-pointer"
              onClick={() => setEditingNote(note)}
              draggable
              onDragStart={(e) => e.dataTransfer.setData("text/plain", note.id)}
            >
              <TableCell className="max-w-[200px] truncate font-medium text-foreground">
                {stripMarkdown(note.content).slice(0, 60)}
              </TableCell>
              <TableCell className="text-xs">
                {note.tags.length > 0 ? (
                  <span className="flex flex-wrap gap-1">
                    {note.tags.map((t) => {
                      const parts = t.split("/")
                      return (
                        <button
                          key={t}
                          onClick={(e) => { e.stopPropagation(); dispatchTagNavigate(t) }}
                          className="whitespace-nowrap hover:underline"
                          title={`Filter by tag: ${t}`}
                        >
                          <span className="text-primary">{parts[0]}</span>
                          {parts.length > 1 && (
                            <span className="text-muted-foreground">{"/" + parts.slice(1).join("/")}</span>
                          )}
                        </button>
                      )
                    })}
                  </span>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {note.group_name ?? "—"}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {formatDate(note.created_at)}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {note.document_id ? (docTitleMap[note.document_id] ?? note.document_id) : "Standalone"}
              </TableCell>
              <TableCell>
                <button
                  onClick={(e) => { e.stopPropagation(); setEditingNote(note) }}
                  className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-accent"
                  title="Edit"
                >
                  <Pencil size={12} />
                </button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    )
  } else {
    panelContent = (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {noteList.map((note) => (
          <NoteCard
            key={note.id}
            note={note}
            onEdit={() => setEditingNote(note)}
            onDeleted={handleRefetch}
          />
        ))}
      </div>
    )
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left sidebar */}
      <div className="flex w-[280px] shrink-0 flex-col gap-1 overflow-auto border-r border-border p-4">
        <button
          onClick={() => {
            setFilter({ type: "all" })
            setActiveCollectionId(null)
            setActiveTag(null)
          }}
          className={`flex items-center gap-2 rounded px-3 py-2 text-sm text-left transition-colors ${
            filter.type === "all" && !activeCollectionId && !activeTag
              ? "bg-accent font-medium text-foreground"
              : "text-muted-foreground hover:bg-accent/60"
          }`}
        >
          All Notes
          <span className="ml-auto text-xs">{groups?.total_notes ?? noteList.length}</span>
        </button>

        <button
          onClick={() => {
            setFilter({ type: "journal" })
            setActiveCollectionId(null)
            setActiveTag(null)
          }}
          className={`flex items-center gap-2 rounded px-3 py-2 text-sm text-left transition-colors ${
            filter.type === "journal"
              ? "bg-accent font-medium text-foreground"
              : "text-muted-foreground hover:bg-accent/60"
          }`}
        >
          <BookOpen size={13} />
          Reading Journal
        </button>

        {/* Collections section */}
        <div className="mt-3">
          <div className="mb-1 flex items-center justify-between px-1">
            <p className="px-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Collections
            </p>
            <button
              onClick={() => setShowCreateCollection(true)}
              className="rounded p-0.5 text-muted-foreground hover:text-foreground hover:bg-accent"
              title="New collection"
            >
              <Plus size={12} />
            </button>
          </div>
          <CollectionTree />
          <button
            onClick={() => setShowCreateCollection(true)}
            className="mt-1 flex w-full items-center gap-1 rounded px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent/60 hover:text-foreground"
          >
            <Plus size={11} />
            New Collection
          </button>
        </div>

        {/* Tags section */}
        <div className="mt-3">
          <div className="mb-1 flex items-center justify-between px-1">
            <p className="px-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Tags
            </p>
          </div>
          <TagTree />
        </div>

        {/* Suggested Collections summary + auto-organize trigger */}
        {(clusterSuggestions.length > 0 || isClusterQueued) && (
          <div className="mt-3">
            <div className="mb-1 flex items-center justify-between px-1">
              <p className="px-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Suggested Collections
              </p>
              <button
                onClick={() => void handleAutoOrganize()}
                disabled={isClusterQueued}
                className="rounded p-0.5 text-muted-foreground hover:text-foreground hover:bg-accent disabled:opacity-50"
                title="Auto-organize notes into collections"
              >
                {isClusterQueued ? <Loader2 size={12} className="animate-spin" /> : <Wand2 size={12} />}
              </button>
            </div>
            {clusterSuggestionsLoading && (
              <div className="space-y-1.5 px-1">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="h-12 animate-pulse rounded bg-accent/40" />
                ))}
              </div>
            )}
            {clusterSuggestionsError && (
              <p className="px-3 text-xs text-amber-500">
                Could not load suggestions.{" "}
                <button onClick={() => void refetchClusterSuggestions()} className="underline">
                  Retry
                </button>
              </p>
            )}
            {clusterSuggestions.length > 0 && !clusterSuggestionsLoading && (
              <button
                onClick={() => setShowOrgPlan(true)}
                className="w-full rounded border border-border p-2 text-xs text-left hover:bg-accent/40"
              >
                <span className="font-medium">
                  {clusterSuggestions.length} group{clusterSuggestions.length !== 1 ? "s" : ""} found
                </span>
                <span className="text-muted-foreground"> -- click to review plan</span>
              </button>
            )}
          </div>
        )}

        {/* Auto-organize button (always visible even when no suggestions) */}
        {clusterSuggestions.length === 0 && !isClusterQueued && (
          <div className="mt-3">
            <button
              onClick={() => void handleAutoOrganize()}
              className="flex w-full items-center gap-1 rounded px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent/60 hover:text-foreground"
              title="Auto-organize notes into suggested collections"
            >
              <Wand2 size={11} />
              Auto-organize
            </button>
          </div>
        )}

        {/* Organization Plan dialog */}
        <OrganizationPlanDialog
          open={showOrgPlan}
          onOpenChange={setShowOrgPlan}
          suggestions={clusterSuggestions}
          onApplied={() => {
            void qc.invalidateQueries({ queryKey: ["clusterSuggestions"] })
            void qc.invalidateQueries({ queryKey: ["collections"] })
            void qc.invalidateQueries({ queryKey: ["collections-tree"] })
            toast.success("Organization plan applied")
          }}
          onDismissed={() => {
            void qc.invalidateQueries({ queryKey: ["clusterSuggestions"] })
          }}
        />
      </div>

      {/* Right panel */}
      <div className="flex-1 overflow-auto p-6">
        {/* Panel header with view toggle + button */}
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

        {panelContent}
      </div>

      {/* NoteReaderSheet — rendered once at page level for both View and Create */}
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
            void fetch(`${API_BASE}/collections/${activeCollectionId}/notes`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ note_ids: [savedNote.id] }),
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
