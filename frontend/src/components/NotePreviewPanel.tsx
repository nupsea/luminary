/**
 * NotePreviewPanel: right-side sliding panel shown when a Note node is clicked in Viz.
 *
 * Fetches GET /notes/{noteId} and displays:
 *   - Note content preview
 *   - Tags as chips
 *   - Collection count
 *   - "Open in Notes tab" button that fires luminary:navigate (I-11)
 *
 * S172: Note nodes in Viz Knowledge graph
 */
import { useQuery } from "@tanstack/react-query"
import { X } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"
import { API_BASE } from "@/lib/config"
import { navigateToNote } from "@/lib/noteGraphUtils"

interface NoteDetail {
  id: string
  content: string
  tags: string[]
  collection_ids: string[]
  document_id: string | null
}

interface NotePreviewPanelProps {
  noteId: string
  onClose: () => void
}

async function fetchNote(noteId: string): Promise<NoteDetail> {
  const res = await fetch(`${API_BASE}/notes/${noteId}`)
  if (!res.ok) throw new Error("Failed to fetch note")
  return res.json() as Promise<NoteDetail>
}

export default function NotePreviewPanel({ noteId, onClose }: NotePreviewPanelProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["note-preview", noteId],
    queryFn: () => fetchNote(noteId),
    staleTime: 30_000,
  })

  const openInNotesTab = () => {
    // I-11: cross-tab navigation via luminary:navigate DOM event (via noteGraphUtils)
    navigateToNote(noteId)
    onClose()
  }

  return (
    <div
      className="absolute right-0 top-0 bottom-0 w-72 flex flex-col border-l border-border bg-background shadow-lg z-20"
      style={{ overflow: "hidden" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Note
        </span>
        <button
          onClick={onClose}
          className="rounded p-0.5 text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          aria-label="Close note panel"
        >
          <X size={14} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-3">
        {isLoading && (
          <>
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-2/3" />
          </>
        )}

        {isError && (
          <p className="text-sm text-red-600">Could not load note.</p>
        )}

        {data && (
          <>
            {/* Content preview */}
            <p className="text-sm text-foreground whitespace-pre-wrap line-clamp-12">
              {data.content}
            </p>

            {/* Tags */}
            {data.tags.length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1">Tags</p>
                <div className="flex flex-wrap gap-1">
                  {data.tags.map((tag) => (
                    <span
                      key={tag}
                      className="inline-block rounded bg-accent px-1.5 py-0.5 text-xs text-accent-foreground"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Collections */}
            {data.collection_ids.length > 0 && (
              <p className="text-xs text-muted-foreground">
                In {data.collection_ids.length}{" "}
                {data.collection_ids.length === 1 ? "collection" : "collections"}
              </p>
            )}
          </>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-border">
        <button
          onClick={openInNotesTab}
          disabled={!data}
          className="w-full rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
        >
          Open in Notes tab
        </button>
      </div>
    </div>
  )
}
