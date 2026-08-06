import { cn } from "@/lib/utils"

interface PanelResizerProps {
  onPointerDown: (e: React.PointerEvent) => void
  dragging: boolean
  label: string
}

/** Drag handle between two panels. 1px seam, wider invisible hit area. */
export function PanelResizer({ onPointerDown, dragging, label }: PanelResizerProps) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      onPointerDown={onPointerDown}
      className={cn(
        "group relative z-30 w-1 shrink-0 cursor-col-resize bg-border transition-colors",
        dragging ? "bg-primary" : "hover:bg-primary/60",
      )}
    >
      <span className="absolute inset-y-0 -left-1.5 -right-1.5 block" />
    </div>
  )
}
