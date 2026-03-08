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
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
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

async function deleteNote(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/notes/${id}`, { method: "DELETE" })
  if (!res.ok && res.status !== 204) throw new Error(`DELETE /notes/${id} failed: ${res.status}`)
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
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["notes-groups"] })
      onCreated()
      onClose()
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
// NoteEditorTabs — Write / Preview tab editor for note content
// ---------------------------------------------------------------------------

interface NoteEditorTabsProps {
  value: string
  onChange: (v: string) => void
  onSave: () => void
  onCancel: () => void
  isPending: boolean
}

function NoteEditorTabs({ value, onChange, onSave, onCancel, isPending }: NoteEditorTabsProps) {
  const [tab, setTab] = useState<"write" | "preview">("write")
  const taRef = useRef<HTMLTextAreaElement>(null)

  const adjustHeight = useCallback(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = "auto"
    ta.style.height = `${ta.scrollHeight}px`
  }, [])

  useEffect(() => {
    if (tab === "write") adjustHeight()
  }, [value, tab, adjustHeight])

  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-1 rounded-md bg-muted p-0.5 text-xs w-fit">
        <button
          onClick={() => setTab("write")}
          className={`rounded px-2.5 py-1 font-medium transition-colors ${
            tab === "write" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Write
        </button>
        <button
          onClick={() => setTab("preview")}
          className={`rounded px-2.5 py-1 font-medium transition-colors ${
            tab === "preview" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Preview
        </button>
      </div>
      {tab === "write" ? (
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => { onChange(e.target.value); adjustHeight() }}
          className="min-h-[200px] w-full resize-none overflow-hidden rounded border border-border bg-background px-2 py-1.5 font-mono text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
      ) : (
        <div className="min-h-[200px] rounded border border-border bg-background px-2 py-2">
          {value ? (
            <MarkdownRenderer>{value}</MarkdownRenderer>
          ) : (
            <p className="text-sm text-muted-foreground">Nothing to preview yet.</p>
          )}
        </div>
      )}
      <div className="flex gap-2">
        <button
          onClick={onSave}
          disabled={!value.trim() || isPending}
          className="flex items-center gap-1 rounded bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          <Check size={11} />
          Save
        </button>
        <button
          onClick={onCancel}
          className="rounded border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// NoteCard
// ---------------------------------------------------------------------------

interface NoteCardProps {
  note: Note
  onUpdated: () => void
  onDeleted: () => void
}

function NoteCard({ note, onUpdated, onDeleted }: NoteCardProps) {
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [content, setContent] = useState(note.content)
  const qc = useQueryClient()

  const saveMut = useMutation({
    mutationFn: () => patchNote(note.id, { content }),
    onSuccess: () => {
      setEditing(false)
      void qc.invalidateQueries({ queryKey: ["notes"] })
      onUpdated()
    },
  })

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
          onClick={() => { setEditing((v) => !v); setConfirming(false) }}
          className="hover:text-foreground"
          title="Edit"
        >
          <Pencil size={12} />
        </button>
        <button
          onClick={() => { setConfirming((v) => !v); setEditing(false) }}
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

      {/* Content */}
      {editing ? (
        <div className="flex flex-col gap-2">
          {/* Write / Preview tabs */}
          <NoteEditorTabs
            value={content}
            onChange={setContent}
            onSave={() => saveMut.mutate()}
            onCancel={() => { setEditing(false); setContent(note.content) }}
            isPending={saveMut.isPending}
          />
        </div>
      ) : (
        !confirming && (
          <div
            className="cursor-pointer"
            onClick={() => setEditing(true)}
          >
            <MarkdownRenderer>{note.content.slice(0, 200)}</MarkdownRenderer>
          </div>
        )
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
  const [showCreate, setShowCreate] = useState(false)
  const [editingNote, setEditingNote] = useState<Note | null>(null)
  const [editingContent, setEditingContent] = useState("")
  const qc = useQueryClient()
  const mountTime = useRef(Date.now())

  const inlineEditMut = useMutation({
    // Receive values explicitly so the mutationFn never closes over stale state.
    // Calling mutate() with no args (old pattern) would capture editingNote=null
    // from the initial render, causing a runtime TypeError on the ! assertion.
    mutationFn: ({ id, content }: { id: string; content: string }) =>
      patchNote(id, { content }),
    onSuccess: () => {
      setEditingNote(null)
      void qc.invalidateQueries({ queryKey: ["notes"] })
    },
  })

  useEffect(() => {
    if (editingNote) {
      setEditingContent(editingNote.content)
      inlineEditMut.reset()
    }
    // inlineEditMut.reset is stable; editingNote drives all changes here
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingNote])
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

  if (notesLoading) {
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
                {note.content.slice(0, 60)}
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
            onUpdated={handleRefetch}
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
            <ViewToggle value={notesView} onChange={setNotesView} />
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

        {editingNote && (
          <div className="mt-4 rounded-lg border border-border bg-card p-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm font-medium text-foreground">Edit Note</span>
              <button
                onClick={() => { setEditingNote(null); setEditingContent("") }}
                className="text-muted-foreground hover:text-foreground"
                title="Close"
              >
                <X size={14} />
              </button>
            </div>
            <NoteEditorTabs
              key={editingNote.id}
              value={editingContent}
              onChange={setEditingContent}
              onSave={() => {
                if (editingNote) inlineEditMut.mutate({ id: editingNote.id, content: editingContent })
              }}
              onCancel={() => { setEditingNote(null); setEditingContent("") }}
              isPending={inlineEditMut.isPending}
            />
            {inlineEditMut.isError && (
              <p className="mt-2 text-xs text-red-600">Failed to save. Please try again.</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
