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

export interface SourceRef {
  sectionId: string | undefined
  documentId: string
  documentTitle: string
}

export interface SelectionActionBarProps {
  containerRef: React.RefObject<HTMLElement | null>
  resolveSourceRef: (startContainer: Node) => SourceRef
  onExplain: (text: string, mode: ExplainMode) => void
  onAddToNote: (text: string, sourceRef: SourceRef) => void
  onCreateFlashcard: (text: string, sourceRef: SourceRef) => void
  onAskInChat: (text: string, sourceRef: SourceRef) => void
  onHighlight: (text: string, sourceRef: SourceRef) => void
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

  return (
    <div
      ref={barRef}
      className="fixed z-[100] flex -translate-x-1/2 -translate-y-full gap-1 rounded-lg border border-border bg-background p-1.5 shadow-xl"
      style={{ top: position.top, left: position.left }}
    >
      <button
        onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); onExplain(selectedText, "plain"); reset() }}
        className="rounded px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
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
      <button
        onMouseDown={(e) => {
          e.preventDefault(); e.stopPropagation()
          if (!canHighlight) return
          onHighlight(selectedText, pendingSourceRef); reset()
        }}
        disabled={!canHighlight}
        title={canHighlight ? "Highlight this text" : "Highlight not available without section mapping"}
        className="rounded px-2.5 py-1 text-xs font-medium text-yellow-700 hover:bg-yellow-100 disabled:cursor-not-allowed disabled:opacity-40 dark:text-yellow-400 dark:hover:bg-yellow-900/30"
      >
        Highlight
      </button>
    </div>
  )
}
