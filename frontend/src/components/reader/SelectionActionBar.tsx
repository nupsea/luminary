/**
 * SelectionActionBar -- unified text-selection popup for DocumentReader (S147).
 *
 * Listens on document for mousedown/mouseup to track drag selections.
 * Uses the mouseup event coordinates for positioning (not range.getBoundingClientRect,
 * which can return zero-size rects for PDF text layer transparent spans).
 * Fixed positioning avoids clipping by overflow:hidden ancestors.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import type { ExplainMode } from "@/components/FloatingToolbar"

export type HighlightColor = "yellow" | "green" | "blue" | "pink"

const HIGHLIGHT_SWATCHES: { color: HighlightColor; bg: string }[] = [
  { color: "yellow", bg: "bg-yellow-300" },
  { color: "green", bg: "bg-green-300" },
  { color: "blue", bg: "bg-blue-300" },
  { color: "pink", bg: "bg-pink-300" },
]

export interface SourceRef {
  sectionId: string | undefined
  documentId: string
  documentTitle: string
  pageNumber?: number
}

/** Maximum character count for highlights. Longer selections can still use other actions. */
const HIGHLIGHT_CHAR_LIMIT = 10_000

/** Approximate height of the bar in pixels (for viewport clamping). */
const BAR_HEIGHT = 44
/** Approximate half-width of the bar in pixels (for viewport clamping). */
const BAR_HALF_WIDTH = 160

export interface SelectionActionBarProps {
  containerRef: React.RefObject<HTMLElement | null>
  resolveSourceRef: (startContainer: Node) => SourceRef
  onExplain: (text: string, mode: ExplainMode) => void
  onAddToNote: (text: string, sourceRef: SourceRef) => void
  onCreateFlashcard: (text: string, sourceRef: SourceRef) => void
  onAskInChat: (text: string, sourceRef: SourceRef) => void
  onHighlight: (text: string, sourceRef: SourceRef, color: HighlightColor) => void
  onClip: (text: string, sourceRef: SourceRef) => void
}

interface Position {
  top: number
  left: number
}

export function SelectionActionBar({
  containerRef,
  resolveSourceRef,
  onExplain,
  onAddToNote,
  onCreateFlashcard,
  onAskInChat,
  onHighlight,
  onClip,
}: SelectionActionBarProps) {
  const [position, setPosition] = useState<Position | null>(null)
  const [selectedText, setSelectedText] = useState("")
  const [pendingSourceRef, setPendingSourceRef] = useState<SourceRef | null>(null)
  const barRef = useRef<HTMLDivElement>(null)
  const isDragging = useRef(false)
  const mouseUpCoords = useRef<{ x: number; y: number }>({ x: 0, y: 0 })

  const reset = useCallback(() => {
    setPosition(null)
    setSelectedText("")
    setPendingSourceRef(null)
  }, [])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    function handleMouseDown(e: MouseEvent) {
      // Clicking on the bar itself -- don't dismiss
      if (barRef.current?.contains(e.target as Node)) return

      // Dismiss any existing bar
      reset()

      // Track if drag started inside our container
      isDragging.current = container!.contains(e.target as Node)
    }

    function handleMouseUp(e: MouseEvent) {
      if (!isDragging.current) return
      isDragging.current = false

      // Save mouse coordinates for positioning the bar
      mouseUpCoords.current = { x: e.clientX, y: e.clientY }

      // Wait for browser to finalize the selection
      requestAnimationFrame(() => {
        const selection = window.getSelection()
        if (!selection || selection.rangeCount === 0) return

        const text = selection.toString().trim()
        if (!text) return

        // Verify selection is inside our container
        const anchorNode = selection.anchorNode
        if (!anchorNode || !container!.contains(anchorNode)) return

        const range = selection.getRangeAt(0)

        // Try range rect first; fall back to mouse coordinates if rect is degenerate
        const rect = range.getBoundingClientRect()
        let top: number
        let left: number
        if (rect.width > 0 && rect.height > 0) {
          top = rect.top - 8
          left = rect.left + rect.width / 2
        } else {
          // Fallback: position above where the user released the mouse
          top = mouseUpCoords.current.y - 16
          left = mouseUpCoords.current.x
        }

        // S198: clamp to viewport bounds so bar is never offscreen
        top = Math.max(8, Math.min(top, window.innerHeight - BAR_HEIGHT - 8))
        left = Math.max(BAR_HALF_WIDTH, Math.min(left, window.innerWidth - BAR_HALF_WIDTH))

        const sourceRef = resolveSourceRef(range.startContainer)
        setPendingSourceRef(sourceRef)
        setSelectedText(text)
        setPosition({ top, left })
      })
    }

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") reset()
    }

    document.addEventListener("mousedown", handleMouseDown, true)
    document.addEventListener("mouseup", handleMouseUp, true)
    document.addEventListener("keydown", handleKeyDown)
    return () => {
      document.removeEventListener("mousedown", handleMouseDown, true)
      document.removeEventListener("mouseup", handleMouseUp, true)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [containerRef, resolveSourceRef, reset])

  if (!position || !selectedText || !pendingSourceRef) return null

  const canHighlight = pendingSourceRef.sectionId !== undefined
  const isOversized = selectedText.length > HIGHLIGHT_CHAR_LIMIT

  return (
    <div
      ref={barRef}
      className="fixed z-[100] flex -translate-x-1/2 -translate-y-full gap-1 rounded-2xl border border-border/50 bg-background/80 backdrop-blur-xl p-1.5 shadow-2xl transition-all duration-200 ease-out"
      style={{ top: position.top, left: position.left }}
    >
      <button
        onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); onExplain(selectedText, "plain"); reset() }}
        className="rounded-xl px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent/80 transition-colors"
      >
        Explain
      </button>
      <button
        onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); onAddToNote(selectedText, pendingSourceRef); reset() }}
        className="rounded px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
      >
        Note
      </button>
      <button
        onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); onCreateFlashcard(selectedText, pendingSourceRef); reset() }}
        className="rounded px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
      >
        Flashcard
      </button>
      <button
        onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); onAskInChat(selectedText, pendingSourceRef); reset() }}
        className="rounded px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
      >
        Ask
      </button>
      <button
        onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); onClip(selectedText, pendingSourceRef); reset() }}
        title="Save to Reading Journal"
        className="rounded px-2.5 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 dark:text-blue-400 dark:hover:bg-blue-900/30"
      >
        Clip
      </button>
      <div className="flex items-center gap-0.5 border-l border-border pl-1.5 ml-0.5">
        {HIGHLIGHT_SWATCHES.map((swatch) => (
          <button
            key={swatch.color}
            onMouseDown={(e) => {
              e.preventDefault(); e.stopPropagation()
              if (!canHighlight || isOversized) return
              onHighlight(selectedText, pendingSourceRef, swatch.color); reset()
            }}
            disabled={!canHighlight || isOversized}
            title={isOversized ? "Selection too long to highlight (max 10,000 chars)" : canHighlight ? `Highlight ${swatch.color}` : "Highlight not available without section mapping"}
            className={`h-5 w-5 rounded-full ${swatch.bg} border border-border/50 disabled:cursor-not-allowed disabled:opacity-40 hover:ring-2 hover:ring-primary/40`}
          />
        ))}
      </div>
    </div>
  )
}
