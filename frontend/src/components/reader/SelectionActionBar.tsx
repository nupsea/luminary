/**
 * SelectionActionBar -- unified text-selection popup for DocumentReader
 *
 * Driven by `selectionchange`, so a drag, double-click, Shift+arrows or a touch
 * selection all raise it. It waits for a drag to be released, follows the
 * selection while the reader scrolls, and flips below when there is no room above.
 * Fixed positioning avoids clipping by overflow:hidden ancestors.
 */

import { useEffect, useRef, useState } from "react"
import { explainModeFor, placeBar, selectionBox, type Placement } from "./selectionBarLogic"

export type ExplainMode = "define" | "plain" | "eli5" | "analogy"

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
  /** The chunk the selection sits in, where the view renders chunk by chunk. */
  chunkId?: string
}

/** Maximum character count for highlights. Longer selections can still use other actions. */
const HIGHLIGHT_CHAR_LIMIT = 10_000

/** Long enough that Shift+arrow extension doesn't flash the bar on every keystroke. */
const SETTLE_MS = 180

export interface SelectionActionBarProps {
  containerRef: React.RefObject<HTMLElement | null>
  resolveSourceRef: (startContainer: Node) => SourceRef
  onExplain: (text: string, mode: ExplainMode) => void
  onAskInChat: (text: string, sourceRef: SourceRef) => void
  onHighlight: (text: string, sourceRef: SourceRef, color: HighlightColor) => void
}

interface Captured {
  text: string
  sourceRef: SourceRef
}

export function SelectionActionBar({
  containerRef,
  resolveSourceRef,
  onExplain,
  onAskInChat,
  onHighlight,
}: SelectionActionBarProps) {
  const [captured, setCaptured] = useState<Captured | null>(null)
  const [placement, setPlacement] = useState<Placement | null>(null)
  const barRef = useRef<HTMLDivElement>(null)
  const dismissRef = useRef<() => void>(() => {})

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    let range: Range | null = null
    let pointerHeld = false
    let pointer = { x: 0, y: 0 }
    let settleTimer = 0
    let frame = 0

    function hide() {
      window.clearTimeout(settleTimer)
      range = null
      setCaptured(null)
      setPlacement(null)
    }
    dismissRef.current = hide

    function place() {
      if (!range) return
      // PDF text-layer spans can yield no line boxes; the release point stands in.
      const box = selectionBox(Array.from(range.getClientRects()))
        ?? { top: pointer.y - 8, bottom: pointer.y + 8, left: pointer.x, right: pointer.x }
      setPlacement(placeBar(box, container!.getBoundingClientRect(), {
        width: window.innerWidth,
        height: window.innerHeight,
      }))
    }

    function capture() {
      const selection = window.getSelection()
      const text = selection?.toString().trim() ?? ""
      if (!selection || selection.rangeCount === 0 || selection.isCollapsed || !text) {
        hide()
        return
      }
      const current = selection.getRangeAt(0)
      if (!container!.contains(current.commonAncestorContainer)) {
        hide()
        return
      }
      range = current.cloneRange()
      setCaptured({ text, sourceRef: resolveSourceRef(current.startContainer) })
      place()
    }

    function settle(delay: number) {
      window.clearTimeout(settleTimer)
      settleTimer = window.setTimeout(capture, delay)
    }

    function handleSelectionChange() {
      if (window.getSelection()?.isCollapsed ?? true) {
        hide()
        return
      }
      // Mid-drag the selection is still moving; the release shows the bar.
      if (!pointerHeld) settle(SETTLE_MS)
    }

    function handlePointerDown(e: PointerEvent) {
      if (barRef.current?.contains(e.target as Node)) return
      pointerHeld = true
      setPlacement(null)
    }

    function handlePointerUp(e: PointerEvent) {
      if (!pointerHeld) return
      pointerHeld = false
      pointer = { x: e.clientX, y: e.clientY }
      settle(0)
    }

    // A touch long-press hands over to the browser's own selection handles.
    function handlePointerCancel() {
      pointerHeld = false
      settle(SETTLE_MS)
    }

    function handleViewportChange() {
      if (!range) return
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(place)
    }

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") hide()
    }

    document.addEventListener("selectionchange", handleSelectionChange)
    document.addEventListener("pointerdown", handlePointerDown, true)
    document.addEventListener("pointerup", handlePointerUp, true)
    document.addEventListener("pointercancel", handlePointerCancel, true)
    // Capture phase: the reader scrolls inside its own panes, and scroll doesn't bubble.
    document.addEventListener("scroll", handleViewportChange, true)
    window.addEventListener("resize", handleViewportChange)
    document.addEventListener("keydown", handleKeyDown)
    return () => {
      window.clearTimeout(settleTimer)
      cancelAnimationFrame(frame)
      document.removeEventListener("selectionchange", handleSelectionChange)
      document.removeEventListener("pointerdown", handlePointerDown, true)
      document.removeEventListener("pointerup", handlePointerUp, true)
      document.removeEventListener("pointercancel", handlePointerCancel, true)
      document.removeEventListener("scroll", handleViewportChange, true)
      window.removeEventListener("resize", handleViewportChange)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [containerRef, resolveSourceRef])

  if (!captured || !placement) return null

  const { text, sourceRef } = captured
  const mode = explainModeFor(text)
  const canHighlight = sourceRef.sectionId !== undefined
  const isOversized = text.length > HIGHLIGHT_CHAR_LIMIT
  // preventDefault on mousedown keeps the selection alive under the click.
  const act = (run: () => void) => (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    run()
    dismissRef.current()
  }

  return (
    <div
      // Re-keyed per selection so the fade plays on a new one, not on every scroll.
      key={text}
      ref={barRef}
      data-testid="selection-action-bar"
      data-side={placement.side}
      className={`fixed z-[100] flex -translate-x-1/2 ${placement.side === "above" ? "-translate-y-full" : ""} gap-1 rounded-2xl border border-border/50 bg-background/80 p-1.5 shadow-2xl backdrop-blur-xl animate-in fade-in-0 duration-150`}
      style={{ top: placement.top, left: placement.left }}
    >
      <button
        onMouseDown={act(() => onExplain(text, mode))}
        title={mode === "define" ? "Define this term as the document uses it" : "Rewrite this passage in plain English"}
        className="rounded-xl px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-accent/80"
      >
        {mode === "define" ? "Define" : "Simplify"}
      </button>
      <button
        onMouseDown={act(() => onAskInChat(text, sourceRef))}
        className="rounded-xl px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-accent/80"
      >
        Ask
      </button>
      <div className="ml-0.5 flex items-center gap-0.5 border-l border-border pl-1.5">
        {HIGHLIGHT_SWATCHES.map((swatch) => (
          <button
            key={swatch.color}
            onMouseDown={(e) => {
              if (!canHighlight || isOversized) {
                e.preventDefault()
                return
              }
              act(() => onHighlight(text, sourceRef, swatch.color))(e)
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
