import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDownLeft, ArrowUpRight, Link2, Trash2 } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"
import {
  deleteNoteLink,
  fetchNoteLinks,
  type NoteLinkItem,
} from "@/lib/notesApi"

interface NoteBacklinksProps {
  noteId: string
  /** Absent = links render read-only (surfaces without note navigation). */
  onOpenNote?: (noteId: string) => void
}

function LinkRow({
  item,
  direction,
  ownerNoteId,
  onOpenNote,
}: {
  item: NoteLinkItem
  direction: "outgoing" | "incoming"
  ownerNoteId: string
  onOpenNote?: (noteId: string) => void
}) {
  const [confirming, setConfirming] = useState(false)
  const qc = useQueryClient()

  async function handleDelete() {
    // item.note_id is always the OTHER note; the link row itself lives on the
    // source side, so incoming deletes go through the other note's id.
    const [src, dst] =
      direction === "outgoing" ? [ownerNoteId, item.note_id] : [item.note_id, ownerNoteId]
    try {
      await deleteNoteLink(src, dst, item.link_type)
    } catch {
      // row stays; refetch below shows the truth either way
    }
    void qc.invalidateQueries({ queryKey: ["note-links", ownerNoteId] })
  }

  return (
    <div className="group flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5">
      {direction === "outgoing" ? (
        <ArrowUpRight size={12} className="shrink-0 text-muted-foreground" />
      ) : (
        <ArrowDownLeft size={12} className="shrink-0 text-muted-foreground" />
      )}
      <button
        type="button"
        disabled={!onOpenNote}
        onClick={() => onOpenNote?.(item.note_id)}
        className={`min-w-0 flex-1 truncate text-left text-xs text-foreground ${
          onOpenNote ? "hover:text-primary hover:underline" : "cursor-default"
        }`}
        title={onOpenNote ? "Open linked note" : undefined}
      >
        {item.preview || "Untitled note"}
      </button>
      <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
        {item.link_type}
      </span>
      {confirming ? (
        <span className="flex shrink-0 items-center gap-1">
          <button
            onClick={() => void handleDelete()}
            className="rounded bg-destructive px-1.5 py-0.5 text-[10px] font-medium text-destructive-foreground hover:bg-destructive/90"
          >
            Remove
          </button>
          <button
            onClick={() => setConfirming(false)}
            className="rounded border border-border px-1.5 py-0.5 text-[10px] hover:bg-accent"
          >
            Keep
          </button>
        </span>
      ) : (
        <button
          onClick={() => setConfirming(true)}
          className="shrink-0 rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
          title="Remove link"
          aria-label="Remove link"
        >
          <Trash2 size={11} />
        </button>
      )}
    </div>
  )
}

export function NoteBacklinks({ noteId, onOpenNote }: NoteBacklinksProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["note-links", noteId],
    queryFn: () => fetchNoteLinks(noteId),
    staleTime: 10_000,
  })

  const outgoing = data?.outgoing ?? []
  const incoming = data?.incoming ?? []

  return (
    <div className="flex shrink-0 flex-col gap-2 border-t border-border pt-3">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Link2 size={12} />
        <span className="text-[10px] font-bold uppercase tracking-wider">Links</span>
      </div>
      {isLoading ? (
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-7 w-full rounded-md" />
          <Skeleton className="h-7 w-2/3 rounded-md" />
        </div>
      ) : outgoing.length === 0 && incoming.length === 0 ? (
        <p className="text-xs italic text-muted-foreground">
          No links yet -- type [[ in the editor to connect notes.
        </p>
      ) : (
        <div className="flex max-h-48 flex-col gap-1.5 overflow-y-auto">
          {outgoing.map((item) => (
            <LinkRow
              key={item.id}
              item={item}
              direction="outgoing"
              ownerNoteId={noteId}
              onOpenNote={onOpenNote}
            />
          ))}
          {incoming.map((item) => (
            <LinkRow
              key={item.id}
              item={item}
              direction="incoming"
              ownerNoteId={noteId}
              onOpenNote={onOpenNote}
            />
          ))}
        </div>
      )}
    </div>
  )
}
