// Bottom-right camera controls for the Viz page: zoom in / zoom out
// / fit to screen. Pure presentation; the page owns the Sigma camera
// methods and passes them in as callbacks.

import { Maximize2, Minus, Plus } from "lucide-react"

interface CameraControlsProps {
  visible: boolean
  onZoomIn: () => void
  onZoomOut: () => void
  onReset: () => void
}

export function CameraControls({
  visible,
  onZoomIn,
  onZoomOut,
  onReset,
}: CameraControlsProps) {
  if (!visible) return null
  return (
    <div className="absolute bottom-4 right-4 flex flex-col gap-1 z-10">
      <button
        onClick={onZoomIn}
        className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background/90 text-foreground shadow-sm hover:bg-accent transition-all backdrop-blur-sm"
        title="Zoom in"
      >
        <Plus size={14} />
      </button>
      <button
        onClick={onZoomOut}
        className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background/90 text-foreground shadow-sm hover:bg-accent transition-all backdrop-blur-sm"
        title="Zoom out"
      >
        <Minus size={14} />
      </button>
      <div className="h-px bg-border/50 mx-1" />
      <button
        onClick={onReset}
        className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background/90 text-foreground shadow-sm hover:bg-accent transition-all backdrop-blur-sm"
        title="Fit to screen"
      >
        <Maximize2 size={14} />
      </button>
    </div>
  )
}
