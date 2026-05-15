import { LayoutGrid, List } from "lucide-react"
import { cn } from "@/lib/utils"
import type { ViewMode } from "./types"

interface ViewToggleProps {
  value: ViewMode
  onChange: (value: ViewMode) => void
}

export function ViewToggle({ value, onChange }: ViewToggleProps) {
  return (
    <div className="flex rounded-md border border-border">
      <button
        onClick={() => onChange("grid")}
        className={cn(
          "flex h-9 w-9 items-center justify-center rounded-l-md transition-colors",
          value === "grid"
            ? "bg-accent text-accent-foreground"
            : "text-muted-foreground hover:bg-accent/50",
        )}
        title="Grid view"
      >
        <LayoutGrid size={16} />
      </button>
      <button
        onClick={() => onChange("list")}
        className={cn(
          "flex h-9 w-9 items-center justify-center rounded-r-md transition-colors",
          value === "list"
            ? "bg-accent text-accent-foreground"
            : "text-muted-foreground hover:bg-accent/50",
        )}
        title="List view"
      >
        <List size={16} />
      </button>
    </div>
  )
}
