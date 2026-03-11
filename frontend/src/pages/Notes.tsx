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
import { Check, FileText, FolderOpen, Network, Pencil, Plus, Tag, Trash2, X } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { GapDetectDialog } from "@/components/GapDetectDialog"
import { GenerateFlashcardsDialog } from "@/components/GenerateFlashcardsDialog"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { NoteEditorDialog } from "@/components/NoteEditorDialog"
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
import { stripMarkdown } from "@/lib/utils"
import { formatDate, relativeDate } from "@/components/library/utils"
import { useAppStore } from "@/store"

const API_BASE = "http://localhost:8000"

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
  created_at: string
  updated_at: string
}

interface GroupInfo { name: string; count: number }
interface TagInfo { name: string; count: number }
interface GroupsData { groups: GroupInfo[]; tags: TagInfo[] }

interface DocumentItem {
  id: string
  title: string
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchNotes(documentId?: string, group?: string, tag?: string): Promise<Note[]> {
  const params = new URLSearchParams()
  if (documentId) params.set("document_id", documentId)
  if (group) params.set("group", group)
  if (tag) params.set("tag", tag)
  const res = await fetch(`${API_BASE}/notes?${params.toString()}`)
  if (!res.ok) throw new Error(`GET /notes failed: ${res.status}`)
  return res.json() as Promise<Note[]>
}

async function fetchGroups(): Promise<GroupsData> {
  const res = await fetch(`${API_BASE}/notes/groups`)
  if (!res.ok) return { groups: [], tags: [] }
  return res.json() as Promise<GroupsData>
}

async function fetchDocumentList(): Promise<DocumentItem[]> {
  const res = await fetch(`${API_BASE}/documents?page_size=200`)
  if (!res.ok) return []
  const data = (await res.json()) as { items?: DocumentItem[] } | DocumentItem[]
  return Array.isArray(data) ? data : (data.items ?? [])
}

async function createNote(payload: {
  content: string
  tags: string[]
  document_id: string | null
}): Promise<Note> {
  const res = await fetch(`${API_BASE}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`POST /notes failed: ${res.status}`)
  return res.json() as Promise<Note>
}

async function deleteNote(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/notes/${id}`, { method: "DELETE" })
  if (!res.ok && res.status !== 204) throw new Error(`DELETE /notes/${id} failed: ${res.status}`)
}

async function patchNote(
  id: string,
  data: { content?: string; tags?: string[]; group_name?: string },
): Promise<Note> {
  const res = await fetch(`${API_BASE}/notes/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`PATCH /notes/${id} failed: ${res.status}`)
  return res.json() as Promise<Note>
}

async function fetchSuggestedTags(id: string): Promise<string[]> {
  try {
    const res = await fetch(`${API_BASE}/notes/${id}/suggest-tags`, { method: "POST" })
    if (!res.ok) return []
    const data = (await res.json()) as { tags: string[] }
    return data.tags ?? []
  } catch {
    return []
  }
}

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
// CreateNoteForm
// ---------------------------------------------------------------------------

interface CreateNoteFormProps {
  documents: DocumentItem[]
  onClose: () => void
  onCreated: () => void
}

function CreateNoteForm({ documents, onClose, onCreated }: CreateNoteFormProps) {
  const [content, setContent] = useState("")
  const [tagsRaw, setTagsRaw] = useState("")
  const [docId, setDocId] = useState<string>("")
  const [createTab, setCreateTab] = useState<"write" | "preview">("write")
  const createTaRef = useRef<HTMLTextAreaElement>(null)
  const qc = useQueryClient()

  const adjustCreateHeight = useCallback(() => {
    const ta = createTaRef.current
    if (!ta) return
    ta.style.height = "auto"
    ta.style.height = `${ta.scrollHeight}px`
  }, [])

  const createMut = useMutation({
    mutationFn: () =>
      createNote({
        content,
        tags: tagsRaw
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
        document_id: docId || null,
      }),
    onSuccess: (created: Note) => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["notes-groups"] })
      onCreated()
      onClose()
      // Fire-and-forget: suggest tags and silently patch the new note
      void fetchSuggestedTags(created.id).then(async (suggestions) => {
        if (suggestions.length > 0) {
          try {
            await patchNote(created.id, { tags: suggestions })
            void qc.invalidateQueries({ queryKey: ["notes"] })
          } catch {
            // Non-fatal -- note exists without tags
          }
        }
      })
    },
  })

  return (
    <div className="mb-4 rounded-lg border border-border bg-card p-4 flex flex-col gap-3">
      <div className="flex gap-1 rounded-md bg-muted p-0.5 text-xs w-fit">
        <button
          onClick={() => setCreateTab("write")}
          className={`rounded px-2.5 py-1 font-medium transition-colors ${
            createTab === "write" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Write
        </button>
        <button
          onClick={() => setCreateTab("preview")}
          className={`rounded px-2.5 py-1 font-medium transition-colors ${
            createTab === "preview" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Preview
        </button>
      </div>
      {createTab === "write" ? (
        <textarea
          ref={createTaRef}
          value={content}
          onChange={(e) => { setContent(e.target.value); adjustCreateHeight() }}
          placeholder="Write your note in Markdown..."
          className="min-h-[200px] w-full resize-none overflow-hidden rounded border border-border bg-background px-3 py-2 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
      ) : (
        <div className="min-h-[200px] rounded border border-border bg-background px-3 py-2">
          {content ? (
            <MarkdownRenderer>{content}</MarkdownRenderer>
          ) : (
            <p className="text-sm text-muted-foreground">Nothing to preview yet.</p>
          )}
        </div>
      )}
      <input
        type="text"
        value={tagsRaw}
        onChange={(e) => setTagsRaw(e.target.value)}
        placeholder="Tags (comma-separated, optional)"
        className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
      />
      <select
        value={docId}
        onChange={(e) => setDocId(e.target.value)}
        className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
      >
        <option value="">No document</option>
        {documents.map((d) => (
          <option key={d.id} value={d.id}>
            {d.title}
          </option>
        ))}
      </select>
      {createMut.isError && (
        <p className="text-xs text-red-600">Failed to save note. Please try again.</p>
      )}
      <div className="flex gap-2">
        <button
          onClick={() => createMut.mutate()}
          disabled={!content.trim() || createMut.isPending}
          className="flex items-center gap-1 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          <Check size={11} />
          Save
        </button>
        <button
          onClick={onClose}
          className="rounded border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          Cancel
        </button>
      </div>
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

      {/* Tags */}
      {note.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {note.tags.map((t) => (
            <span
              key={t}
              className="flex items-center gap-0.5 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
            >
              <Tag size={9} />
              {t}
            </span>
          ))}
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
  | { type: "group"; name: string }
  | { type: "tag"; name: string }

export default function NotesPage() {
  const [filter, setFilter] = useState<FilterState>({ type: "all" })
  const navigate = useNavigate()
  const [showCreate, setShowCreate] = useState(false)
  const [editingNote, setEditingNote] = useState<Note | null>(null)
  const [showGenerateFlashcards, setShowGenerateFlashcards] = useState(false)
  const [showGapDetect, setShowGapDetect] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const debouncedQuery = useDebounce(searchQuery, 300)
  const qc = useQueryClient()
  const mountTime = useRef(Date.now())
  const notesView = useAppStore((s) => s.notesView)
  const setNotesView = useAppStore((s) => s.setNotesView)

  useEffect(() => {
    logger.info("[Notes] mounted")
  }, [])

  const { data: groups } = useQuery({
    queryKey: ["notes-groups"],
    queryFn: fetchGroups,
  })

  const { data: documents = [] } = useQuery({
    queryKey: ["notes-documents"],
    queryFn: fetchDocumentList,
    staleTime: 60_000,
  })

  const groupParam = filter.type === "group" ? filter.name : undefined
  const tagParam = filter.type === "tag" ? filter.name : undefined

  const {
    data: notes,
    isLoading: notesLoading,
    isError: notesError,
    refetch,
  } = useQuery({
    queryKey: ["notes", groupParam, tagParam],
    queryFn: () => fetchNotes(undefined, groupParam, tagParam),
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

  useEffect(() => {
    if (!notesLoading) {
      const elapsed = Date.now() - mountTime.current
      logger.info("[Notes] loaded", { duration_ms: elapsed, itemCount: notes?.length ?? 0 })
    }
  }, [notesLoading, notes?.length])

  function handleRefetch() {
    void qc.invalidateQueries({ queryKey: ["notes"] })
    void qc.invalidateQueries({ queryKey: ["notes-groups"] })
  }

  const noteList = notes ?? []

  // Determine right panel content
  let panelContent: React.ReactNode

  if (isSearchMode) {
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
                  {result.tags.map((t) => (
                    <span
                      key={t}
                      className="flex items-center gap-0.5 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                    >
                      <Tag size={9} />
                      {t}
                    </span>
                  ))}
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
    panelContent = (
      <div className="flex flex-col items-center gap-3 py-20 text-center">
        <Network size={32} className="text-muted-foreground/50" />
        <p className="text-base font-medium text-foreground">No notes yet</p>
        <p className="text-sm text-muted-foreground">Click + to create your first note.</p>
        <button
          onClick={() => setShowCreate(true)}
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
            >
              <TableCell className="max-w-[200px] truncate font-medium text-foreground">
                {stripMarkdown(note.content).slice(0, 60)}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {note.tags.length > 0 ? note.tags.join(", ") : "—"}
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
          onClick={() => setFilter({ type: "all" })}
          className={`flex items-center gap-2 rounded px-3 py-2 text-sm text-left transition-colors ${
            filter.type === "all"
              ? "bg-accent font-medium text-foreground"
              : "text-muted-foreground hover:bg-accent/60"
          }`}
        >
          All Notes
          <span className="ml-auto text-xs">{noteList.length}</span>
        </button>

        {(groups?.groups ?? []).map((g) => (
          <div key={g.name}>
            <button
              onClick={() => setFilter({ type: "group", name: g.name })}
              className={`flex w-full items-center gap-2 rounded px-3 py-1.5 text-sm text-left ${
                filter.type === "group" && filter.name === g.name
                  ? "bg-accent font-medium text-foreground"
                  : "text-muted-foreground hover:bg-accent/60"
              }`}
            >
              <FolderOpen size={13} />
              {g.name}
              <span className="ml-auto text-xs">{g.count}</span>
            </button>
          </div>
        ))}

        {(groups?.tags ?? []).length > 0 && (
          <div className="mt-3">
            <p className="mb-1 px-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Tags
            </p>
            {groups!.tags.map((t) => (
              <button
                key={t.name}
                onClick={() => setFilter({ type: "tag", name: t.name })}
                className={`flex w-full items-center gap-2 rounded px-3 py-1.5 text-sm text-left ${
                  filter.type === "tag" && filter.name === t.name
                    ? "bg-accent text-foreground"
                    : "text-muted-foreground hover:bg-accent/60"
                }`}
              >
                <Tag size={11} />
                {t.name}
                <span className="ml-auto text-xs">{t.count}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Right panel */}
      <div className="flex-1 overflow-auto p-6">
        {/* Panel header with view toggle + button */}
        <div className="mb-4 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-foreground">
            {filter.type === "all"
              ? "All Notes"
              : filter.type === "group"
                ? filter.name
                : `#${filter.name}`}
          </h2>
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
              onClick={() => navigate("/chat?q=Find+gaps+in+my+notes")}
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
              onClick={() => setShowCreate((v) => !v)}
              className="flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs text-foreground hover:bg-accent"
              title="New note"
            >
              <Plus size={13} />
              New
            </button>
          </div>
        </div>

        {/* Create form */}
        {showCreate && (
          <CreateNoteForm
            documents={documents}
            onClose={() => setShowCreate(false)}
            onCreated={handleRefetch}
          />
        )}

        {panelContent}
      </div>

      {/* NoteEditorDialog — rendered once at page level */}
      <NoteEditorDialog
        note={editingNote}
        onClose={() => setEditingNote(null)}
        onSaved={() => {
          void qc.invalidateQueries({ queryKey: ["notes"] })
          setEditingNote(null)
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
    </div>
  )
}
