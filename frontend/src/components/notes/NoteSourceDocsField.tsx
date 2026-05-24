import { Skeleton } from "@/components/ui/skeleton"

export interface SourceDocOption {
  id: string
  title: string
}

interface NoteSourceDocsFieldProps {
  documents: SourceDocOption[]
  selectedIds: string[]
  onChange: (next: string[]) => void
  loading?: boolean
  emptyMessage?: string
  className?: string
  maxHeightClass?: string
}

export function NoteSourceDocsField({
  documents,
  selectedIds,
  onChange,
  loading,
  emptyMessage = "Ingest a book to link notes to it",
  className,
  maxHeightClass = "max-h-32",
}: NoteSourceDocsFieldProps) {
  if (loading) {
    return (
      <div className={className ?? "flex flex-col gap-1"}>
        {Array.from({ length: 2 }).map((_, i) => (
          <Skeleton key={i} className="h-5 w-full rounded" />
        ))}
      </div>
    )
  }
  if (documents.length === 0) {
    return <p className="text-xs text-muted-foreground">{emptyMessage}</p>
  }
  return (
    <div className={className ?? `${maxHeightClass} overflow-y-auto flex flex-col gap-0.5`}>
      {documents.map((doc) => (
        <label
          key={doc.id}
          className="flex items-center gap-2 cursor-pointer rounded px-1 py-0.5 text-xs text-foreground hover:bg-accent/50"
        >
          <input
            type="checkbox"
            checked={selectedIds.includes(doc.id)}
            onChange={(e) => {
              onChange(
                e.target.checked
                  ? [...selectedIds, doc.id]
                  : selectedIds.filter((id) => id !== doc.id),
              )
            }}
            className="h-3 w-3 rounded border-border"
          />
          <span className="flex-1 truncate">{doc.title}</span>
        </label>
      ))}
    </div>
  )
}
