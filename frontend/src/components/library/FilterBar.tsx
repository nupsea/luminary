import { cn } from "@/lib/utils"
import type { ContentType } from "./types"

const CONTENT_TYPES: ContentType[] = ["book", "paper", "conversation", "notes", "code", "audio"]

const LABELS: Record<ContentType, string> = {
  book: "Book",
  paper: "Paper",
  conversation: "Conversation",
  notes: "Notes",
  code: "Code",
  audio: "Audio",
}

interface FilterBarProps {
  selected: Set<ContentType>
  onChange: (selected: Set<ContentType>) => void
}

export function FilterBar({ selected, onChange }: FilterBarProps) {
  function toggle(type: ContentType) {
    const next = new Set(selected)
    if (next.has(type)) {
      next.delete(type)
    } else {
      next.add(type)
    }
    onChange(next)
  }

  return (
    <div className="flex flex-wrap gap-2">
      {CONTENT_TYPES.map((type) => (
        <button
          key={type}
          onClick={() => toggle(type)}
          className={cn(
            "rounded-full px-3 py-1 text-xs font-medium transition-colors",
            selected.has(type)
              ? "bg-primary text-primary-foreground"
              : "bg-secondary text-secondary-foreground hover:bg-secondary/80",
          )}
        >
          {LABELS[type]}
        </button>
      ))}
    </div>
  )
}
