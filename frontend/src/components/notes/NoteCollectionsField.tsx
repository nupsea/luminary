import { Skeleton } from "@/components/ui/skeleton"
import type { CollectionTreeItem } from "@/lib/collectionUtils"

export interface CollectionOption {
  id: string
  name: string
  color: string
}

interface NoteCollectionsFieldProps {
  collections: CollectionOption[] | CollectionTreeItem[]
  checkedIds: Set<string>
  onToggle: (collectionId: string, checked: boolean) => void
  loading?: boolean
  lockedCollectionId?: string | null
  disabled?: boolean
  disabledTitle?: string
  className?: string
  maxHeightClass?: string
}

export function NoteCollectionsField({
  collections,
  checkedIds,
  onToggle,
  loading,
  lockedCollectionId,
  disabled,
  disabledTitle,
  className,
  maxHeightClass = "max-h-40",
}: NoteCollectionsFieldProps) {
  if (loading) {
    return (
      <div className={className ?? "flex flex-col gap-1"}>
        {Array.from({ length: 2 }).map((_, i) => (
          <Skeleton key={i} className="h-5 w-full rounded" />
        ))}
      </div>
    )
  }
  if (collections.length === 0) {
    return <p className="text-xs text-muted-foreground">No collections yet</p>
  }
  return (
    <div className={className ?? `${maxHeightClass} overflow-y-auto flex flex-col gap-0.5`}>
      {collections.map((col) => {
        const isLocked = col.id === lockedCollectionId
        const isDisabled = Boolean(disabled || isLocked)
        const title = isLocked
          ? "This collection is linked to the current document"
          : disabled
            ? disabledTitle ?? ""
            : ""
        return (
          <label
            key={col.id}
            className={`flex items-center gap-2 cursor-pointer rounded px-1 py-0.5 text-xs text-foreground hover:bg-accent/50 ${isDisabled ? "opacity-75" : ""}`}
            title={title}
          >
            <input
              type="checkbox"
              checked={checkedIds.has(col.id) || isLocked}
              onChange={(e) => onToggle(col.id, e.target.checked)}
              disabled={isDisabled}
              className="h-3 w-3 rounded border-border"
            />
            <span
              className="h-2 w-2 shrink-0 rounded-sm"
              style={{ backgroundColor: col.color }}
            />
            <span className="flex-1 truncate">{col.name}</span>
          </label>
        )
      })}
    </div>
  )
}
