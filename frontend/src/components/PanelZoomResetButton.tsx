import { RotateCcw } from "lucide-react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import {
  formatZoomPercentage,
  getCustomZoomHandler,
  getPanelDisplayName,
  usePanelZoomStore,
} from "@/store/panelZoomStore"

export interface PanelZoomResetButtonProps {
  panelId: string
  className?: string
  /** Whether to display the percentage badge. Default: true */
  showLabel?: boolean
}

export function PanelZoomResetButton({
  panelId,
  className,
  showLabel = true,
}: PanelZoomResetButtonProps) {
  const zoom = usePanelZoomStore((s) => s.getZoom(panelId))
  const resetZoom = usePanelZoomStore((s) => s.resetZoom)

  if (zoom === 1.0) return null

  function handleReset(e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()

    const customHandler = getCustomZoomHandler(panelId)
    if (customHandler && customHandler("reset") === true) {
      return
    }

    const { panelId: id, zoom: nextZoom } = resetZoom(panelId)
    toast(`${getPanelDisplayName(id)}: ${formatZoomPercentage(nextZoom)}`, {
      id: `panel-zoom-${id}`,
      duration: 1200,
    })
  }

  const panelName = getPanelDisplayName(panelId)

  return (
    <button
      type="button"
      onClick={handleReset}
      title={`Reset ${panelName.toLowerCase()} zoom to 100% (Cmd+0 / Ctrl+0)`}
      aria-label={`Reset ${panelName.toLowerCase()} zoom to 100%`}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-border bg-background/80 px-1.5 py-0.5 text-xs text-muted-foreground backdrop-blur hover:bg-accent hover:text-foreground transition-colors",
        className,
      )}
    >
      <RotateCcw size={11} className="shrink-0" />
      {showLabel && (
        <span className="font-mono text-[10px] tabular-nums">
          {formatZoomPercentage(zoom)}
        </span>
      )}
    </button>
  )
}
