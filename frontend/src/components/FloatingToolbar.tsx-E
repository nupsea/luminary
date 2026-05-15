/**
 * FloatingToolbar — appears above selected text in the document reader.
 *
 * Listens for mouseup on its container ref, checks window.getSelection(),
 * and positions itself using getBoundingClientRect() on the selection range.
 */

import { useEffect, useRef, useState } from "react"

export type ExplainMode = "plain" | "eli5" | "analogy"

export interface HighlightInfo {
  text: string
  sectionId: string // data-section-id of the nearest ancestor li
  startOffset: number // character offset within the section preview text
  endOffset: number
  // Toolbar position (relative to container) for positioning the popover
  x: number
  y: number
}

interface FloatingToolbarProps {
  containerRef: React.RefObject<HTMLElement | null>
  onExplain: (text: string, mode: ExplainMode) => void
  onHighlight?: (info: HighlightInfo) => void
}

interface Position {
  top: number
  left: number
}

const TOOLBAR_BUTTONS: { label: string; mode: ExplainMode }[] = [
  { label: "Explain", mode: "plain" },
  { label: "ELI5", mode: "eli5" },
  { label: "Analogy", mode: "analogy" },
]

export function FloatingToolbar({ containerRef, onExplain, onHighlight }: FloatingToolbarProps) {
  const [position, setPosition] = useState<Position | null>(null)
  const [selectedText, setSelectedText] = useState("")
  const toolbarRef = useRef<HTMLDivElement>(null)
  const pendingHighlightInfo = useRef<HighlightInfo | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    const nonNullContainer = container!

    function handleMouseUp(e: MouseEvent) {
      // Ignore clicks inside the toolbar itself
      if (toolbarRef.current?.contains(e.target as Node)) return

      setTimeout(() => {
        const selection = window.getSelection()
        const text = selection?.toString().trim() ?? ""

        if (!text || !selection || selection.rangeCount === 0) {
          setPosition(null)
          setSelectedText("")
          pendingHighlightInfo.current = null
          return
        }

        const range = selection.getRangeAt(0)
        const rect = range.getBoundingClientRect()
        const containerRect = nonNullContainer.getBoundingClientRect()

        // Compute highlight offsets within section preview
        if (onHighlight) {
          // Walk up from startContainer to find [data-section-id] li
          let node: Node | null = range.startContainer
          let sectionId = ""
          while (node) {
            if (node instanceof HTMLElement && node.dataset["sectionId"]) {
              sectionId = node.dataset["sectionId"]
              break
            }
            node = node.parentElement
          }
          // Find preview <p> text within that li
          const previewEl = (node as HTMLElement | null)?.querySelector("p.section-preview")
          const previewText = previewEl?.textContent ?? ""
          const selText = text
          const startOffset = previewText.indexOf(selText)
          const endOffset = startOffset >= 0 ? startOffset + selText.length : -1

          const toolbarTop = rect.top - containerRect.top - 44
          const toolbarLeft = rect.left - containerRect.left + rect.width / 2
          if (sectionId && startOffset >= 0) {
            pendingHighlightInfo.current = {
              text: selText,
              sectionId,
              startOffset,
              endOffset,
              x: toolbarLeft,
              y: toolbarTop,
            }
          } else {
            pendingHighlightInfo.current = null
          }
        }

        setSelectedText(text)
        setPosition({
          top: rect.top - containerRect.top - 44, // 44px above selection
          left: rect.left - containerRect.left + rect.width / 2,
        })
      }, 10)
    }

    function handleMouseDown(e: MouseEvent) {
      if (toolbarRef.current?.contains(e.target as Node)) return
      setPosition(null)
      setSelectedText("")
      pendingHighlightInfo.current = null
    }

    nonNullContainer.addEventListener("mouseup", handleMouseUp)
    document.addEventListener("mousedown", handleMouseDown)
    return () => {
      nonNullContainer.removeEventListener("mouseup", handleMouseUp)
      document.removeEventListener("mousedown", handleMouseDown)
    }
  }, [containerRef, onHighlight])

  if (!position || !selectedText) return null

  return (
    <div
      ref={toolbarRef}
      className="absolute z-50 flex -translate-x-1/2 gap-1 rounded-md border border-border bg-popover p-1 shadow-lg"
      style={{ top: position.top, left: position.left }}
    >
      {TOOLBAR_BUTTONS.map(({ label, mode }) => (
        <button
          key={mode}
          onMouseDown={(e) => {
            e.preventDefault() // Prevent clearing selection
            onExplain(selectedText, mode)
            setPosition(null)
            setSelectedText("")
          }}
          className="rounded px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
        >
          {label}
        </button>
      ))}
      {onHighlight && pendingHighlightInfo.current && (
        <button
          onMouseDown={(e) => {
            e.preventDefault()
            if (pendingHighlightInfo.current) {
              onHighlight(pendingHighlightInfo.current)
            }
            setPosition(null)
            setSelectedText("")
            pendingHighlightInfo.current = null
          }}
          className="rounded px-2.5 py-1 text-xs font-medium text-yellow-700 hover:bg-yellow-100 dark:text-yellow-400 dark:hover:bg-yellow-900/30"
        >
          Highlight
        </button>
      )}
    </div>
  )
}
