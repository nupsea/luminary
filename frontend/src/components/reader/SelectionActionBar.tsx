/**
 * SelectionActionBar — unified text-selection popup for DocumentReader (S147).
 *
 * Fires on mouseup/touchend within containerRef, positions 8px above the
 * selection using getBoundingClientRect, and offers 5 actions:
 *   Explain | Add to Note | Flashcard | Ask in Chat | Highlight
 *
 * Dismisses on Escape keydown or mousedown outside the bar.
 */

import { useEffect, useRef, useState } from "react"
import type { ExplainMode } from "@/components/FloatingToolbar"

export interface SourceRef {
  sectionId: string | undefined // undefined for PDF text layer without section mapping
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
}: SelectionActionBarProps) {
  const [position, setPosition] = useState<Position | null>(null)
  const [selectedText, setSelectedText] = useState("")
  const [pendingSourceRef, setPendingSourceRef] = useState<SourceRef | null>(null)
  const barRef = useRef<HTMLDivElement>(null)

  function reset() {
    setPosition(null)
    setSelectedText("")
    setPendingSourceRef(null)
  }

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    function handleSelectionEnd() {
      setTimeout(() => {
        if (!container) return

        const selection = window.getSelection()
        const text = selection?.toString().trim() ?? ""

        if (!text || !selection || selection.rangeCount === 0) {
          reset()
          return
        }

        const range = selection.getRangeAt(0)
        const rect = range.getBoundingClientRect()
        const containerRect = container.getBoundingClientRect()

        const sourceRef = resolveSourceRef(range.startContainer)
        setPendingSourceRef(sourceRef)
        setSelectedText(text)
        // Position bar: centered horizontally above the selection.
        // The style applies `top - 8` for an 8px gap; translateY(-100%) shifts
        // the bar above the anchor point so it sits clear of the selection.
        setPosition({
          top: rect.top - containerRect.top,
          left: rect.left - containerRect.left + rect.width / 2,
        })
      }, 10)
    }

    container.addEventListener("mouseup", handleSelectionEnd)
    container.addEventListener("touchend", handleSelectionEnd)
    return () => {
      container.removeEventListener("mouseup", handleSelectionEnd)
      container.removeEventListener("touchend", handleSelectionEnd)
    }
  }, [containerRef, resolveSourceRef])

  // Dismiss on outside mousedown
  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (barRef.current?.contains(e.target as Node)) return
      reset()
    }
    document.addEventListener("mousedown", handleMouseDown)
    return () => document.removeEventListener("mousedown", handleMouseDown)
  }, [])

  // Dismiss on Escape
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") reset()
    }
    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [])

  if (!position || !selectedText || !pendingSourceRef) return null

  const canHighlight = pendingSourceRef.sectionId !== undefined

  return (
    <div
      ref={barRef}
      className="absolute z-50 flex -translate-x-1/2 -translate-y-full gap-0.5 rounded-md border border-border bg-popover p-1 shadow-lg"
      style={{ top: position.top - 8, left: position.left }}
    >
      {/* Explain */}
      <button
        onMouseDown={(e) => {
          e.preventDefault()
          onExplain(selectedText, "plain")
          reset()
        }}
        className="rounded px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
      >
        Explain
      </button>

      {/* Add to Note */}
      <button
        onMouseDown={(e) => {
          e.preventDefault()
          onAddToNote(selectedText, pendingSourceRef)
          reset()
        }}
        className="rounded px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
      >
        Note
      </button>

      {/* Create Flashcard */}
      <button
        onMouseDown={(e) => {
          e.preventDefault()
          onCreateFlashcard(selectedText, pendingSourceRef)
          reset()
        }}
        className="rounded px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
      >
        Flashcard
      </button>

      {/* Ask in Chat */}
      <button
        onMouseDown={(e) => {
          e.preventDefault()
          onAskInChat(selectedText, pendingSourceRef)
          reset()
        }}
        className="rounded px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
      >
        Ask
      </button>

      {/* Highlight — disabled when sectionId is undefined (PDF without section mapping) */}
      <button
        onMouseDown={(e) => {
          e.preventDefault()
          if (!canHighlight) return
          onHighlight(selectedText, pendingSourceRef)
          reset()
        }}
        disabled={!canHighlight}
        title={
          canHighlight
            ? "Highlight this text"
            : "Highlight not available without section mapping"
        }
        className="rounded px-2.5 py-1 text-xs font-medium text-yellow-700 hover:bg-yellow-100 disabled:cursor-not-allowed disabled:opacity-40 dark:text-yellow-400 dark:hover:bg-yellow-900/30"
      >
        Highlight
      </button>
    </div>
  )
}
