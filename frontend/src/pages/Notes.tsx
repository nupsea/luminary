/**
 * /notes — standalone notes management page with two-column layout.
 *
 * Left sidebar: group + tag tree from GET /notes/groups.
 * Right panel: grid of NoteCard components with inline editing.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { FileText, Tag, FolderOpen, Pencil, X, Check } from "lucide-react"
import ReactMarkdown from "react-markdown"
import { useState } from "react"
import { relativeDate } from "@/components/library/utils"

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

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function fetchNotes(documentId?: string, group?: string, tag?: string): Promise<Note[]> {
  const params = new URLSearchParams()
  if (documentId) params.set("document_id", documentId)
  if (group) params.set("group", group)
  if (tag) params.set("tag", tag)
  const res = await fetch(`${API_BASE}/notes?${params.toString()}`)
  if (!res.ok) return []
  return res.json() as Promise<Note[]>
}

async function fetchGroups(): Promise<GroupsData> {
  const res = await fetch(`${API_BASE}/notes/groups`)
  if (!res.ok) return { groups: [], tags: [] }
  return res.json() as Promise<GroupsData>
}

async function updateNote(
  id: string,
  data: { content?: string; tags?: string[]; group_name?: string },
): Promise<Note> {
  const res = await fetch(`${API_BASE}/notes/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  return res.json() as Promise<Note>
}

async function deleteNote(id: string): Promise<void> {
  await fetch(`${API_BASE}/notes/${id}`, { method: "DELETE" })
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
  const [content, setContent] = useState(note.content)
  const qc = useQueryClient()

  const saveMut = useMutation({
    mutationFn: () => updateNote(note.id, { content }),
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
          onClick={() => setEditing((v) => !v)}
          className="hover:text-foreground"
          title="Edit"
        >
          <Pencil size={12} />
        </button>
        <button
          onClick={() => deleteMut.mutate()}
          className="hover:text-destructive"
          title="Delete"
        >
          <X size={12} />
        </button>
      </div>

      {/* Content */}
      {editing ? (
        <div className="flex flex-col gap-2">
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="min-h-[80px] w-full rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <div className="flex gap-2">
            <button
              onClick={() => saveMut.mutate()}
              className="flex items-center gap-1 rounded bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            >
              <Check size={11} />
              Save
            </button>
            <button
              onClick={() => { setEditing(false); setContent(note.content) }}
              className="rounded border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div
          className="prose prose-sm max-w-none cursor-pointer text-foreground"
          onClick={() => setEditing(true)}
        >
          <ReactMarkdown>{note.content.slice(0, 200)}</ReactMarkdown>
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
  const qc = useQueryClient()

  const { data: groups } = useQuery({
    queryKey: ["notes-groups"],
    queryFn: fetchGroups,
  })

  const groupParam = filter.type === "group" ? filter.name : undefined
  const tagParam = filter.type === "tag" ? filter.name : undefined

  const { data: notes } = useQuery({
    queryKey: ["notes", groupParam, tagParam],
    queryFn: () => fetchNotes(undefined, groupParam, tagParam),
  })

  function refetch() {
    void qc.invalidateQueries({ queryKey: ["notes"] })
    void qc.invalidateQueries({ queryKey: ["notes-groups"] })
  }

  const noteList = notes ?? []

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
        {noteList.length === 0 ? (
          <div className="flex flex-col items-center py-20 text-center">
            <p className="text-sm text-muted-foreground">No notes yet.</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Open a document and add notes to sections.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {noteList.map((note) => (
              <NoteCard
                key={note.id}
                note={note}
                onUpdated={refetch}
                onDeleted={refetch}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
