// NotesPanel -- main content slot of the Notes page. Picks one of:
//   - <ReadingJournalTab>           (filter.type === "journal")
//   - search results                (debouncedQuery non-empty)
//   - loading skeletons              (notesLoading)
//   - error state                    (notesError)
//   - empty state                    (noteList.length === 0)
//   - <Table> list view              (notesView === "list")
//   - grid of <NoteCard>             (default)
//
// Pure presentation; the parent owns all data + state.

import { Network, Pencil, Tag } from "lucide-react"
import type { ReactNode } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatDate } from "@/components/library/utils"
import { dispatchTagNavigate } from "@/lib/noteNavigateUtils"
import { stripMarkdown } from "@/lib/utils"

import { NoteCard } from "./NoteCard"
import { ReadingJournalTab } from "./ReadingJournalTab"
import type { Clip, DocumentItem, Note, NoteSearchResponse } from "./types"

type FilterState =
  | { type: "all" }
  | { type: "journal" }
  | { type: "group"; name: string }
  | { type: "tag"; name: string }

interface NotesPanelProps {
  filter: FilterState
  // Search
  isSearchMode: boolean
  searchData: NoteSearchResponse | undefined
  searchLoading: boolean
  searchError: boolean
  onRefetchSearch: () => void
  debouncedQuery: string
  // Notes list
  notesLoading: boolean
  notesError: boolean
  onRefetchNotes: () => void
  noteList: Note[]
  notesView: "list" | "grid"
  documents: DocumentItem[]
  // Filters / actions
  activeTag: string | null
  onSetEditingNote: (n: Note) => void
  onStartCreating: () => void
  onConvertClipToNote: (clip: Clip) => Promise<void> | void
  onCreateFlashcardFromClip: (clip: Clip) => Promise<void> | void
  onDeleted: () => void
  navigate: (url: string) => void
}

export function NotesPanel(props: NotesPanelProps): ReactNode {
  const {
    filter,
    isSearchMode,
    searchData,
    searchLoading,
    searchError,
    onRefetchSearch,
    debouncedQuery,
    notesLoading,
    notesError,
    onRefetchNotes,
    noteList,
    notesView,
    documents,
    activeTag,
    onSetEditingNote,
    onStartCreating,
    onConvertClipToNote,
    onCreateFlashcardFromClip,
    onDeleted,
    navigate,
  } = props

  if (filter.type === "journal") {
    return (
      <ReadingJournalTab
        documents={documents}
        onConvertToNote={(clip) => void onConvertClipToNote(clip)}
        onCreateFlashcard={(clip) => void onCreateFlashcardFromClip(clip)}
        navigate={navigate}
      />
    )
  }

  if (isSearchMode) {
    if (searchLoading) {
      return (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      )
    }
    if (searchError) {
      return (
        <div className="flex items-center gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <span className="flex-1">Search failed</span>
          <button
            onClick={onRefetchSearch}
            className="rounded border border-amber-300 bg-white px-3 py-1 text-xs text-amber-700 hover:bg-amber-50"
          >
            Retry
          </button>
        </div>
      )
    }
    if (!searchData || searchData.results.length === 0) {
      return (
        <div className="flex flex-col items-center gap-3 py-20 text-center">
          <p className="text-sm text-muted-foreground">
            No notes matching &ldquo;{debouncedQuery}&rdquo;
          </p>
        </div>
      )
    }
    return (
      <div className="flex flex-col gap-3">
        {searchData.results.map((result) => {
          const matchedNote = noteList.find((n) => n.id === result.note_id)
          return (
            <div
              key={result.note_id}
              className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3 cursor-pointer hover:bg-accent/50"
              onClick={() => {
                if (matchedNote) onSetEditingNote(matchedNote)
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
                      onClick={(e) => {
                        e.stopPropagation()
                        dispatchTagNavigate(t)
                      }}
                      className="flex items-center gap-0.5 rounded-full bg-muted px-2 py-0.5 text-xs hover:bg-accent transition-colors"
                      title={`Filter by tag: ${t}`}
                    >
                      <Tag size={9} className="text-muted-foreground" />
                      <span className="text-primary">{parts[0]}</span>
                      {parts.length > 1 && (
                        <span className="text-muted-foreground">
                          {"/" + parts.slice(1).join("/")}
                        </span>
                      )}
                    </button>
                  )
                })}
                <span className="ml-auto text-xs text-muted-foreground">
                  {result.source === "both"
                    ? "FTS + Semantic"
                    : result.source === "vector"
                      ? "Semantic"
                      : "FTS"}
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

  if (notesLoading) {
    return notesView === "list" ? (
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
              <TableCell>
                <Skeleton className="h-4 w-40" />
              </TableCell>
              <TableCell>
                <Skeleton className="h-4 w-20" />
              </TableCell>
              <TableCell>
                <Skeleton className="h-4 w-16" />
              </TableCell>
              <TableCell>
                <Skeleton className="h-4 w-24" />
              </TableCell>
              <TableCell>
                <Skeleton className="h-4 w-24" />
              </TableCell>
              <TableCell>
                <Skeleton className="h-4 w-8" />
              </TableCell>
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
  }

  if (notesError) {
    return (
      <div className="flex items-center gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <span className="flex-1">Could not load notes</span>
        <button
          onClick={onRefetchNotes}
          className="rounded border border-amber-300 bg-white px-3 py-1 text-xs text-amber-700 hover:bg-amber-50"
        >
          Retry
        </button>
      </div>
    )
  }

  if (noteList.length === 0) {
    return activeTag ? (
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
          onClick={onStartCreating}
          className="flex items-center gap-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground hover:bg-accent"
        >
          <Tag size={14} />
          New note
        </button>
      </div>
    )
  }

  if (notesView === "list") {
    const docTitleMap = Object.fromEntries(documents.map((d) => [d.id, d.title]))
    return (
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
              onClick={() => onSetEditingNote(note)}
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
                          onClick={(e) => {
                            e.stopPropagation()
                            dispatchTagNavigate(t)
                          }}
                          className="whitespace-nowrap hover:underline"
                          title={`Filter by tag: ${t}`}
                        >
                          <span className="text-primary">{parts[0]}</span>
                          {parts.length > 1 && (
                            <span className="text-muted-foreground">
                              {"/" + parts.slice(1).join("/")}
                            </span>
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
                {note.document_id
                  ? (docTitleMap[note.document_id] ?? note.document_id)
                  : "Standalone"}
              </TableCell>
              <TableCell>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onSetEditingNote(note)
                  }}
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
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {noteList.map((note) => (
        <NoteCard
          key={note.id}
          note={note}
          onEdit={() => onSetEditingNote(note)}
          onDeleted={onDeleted}
        />
      ))}
    </div>
  )
}
