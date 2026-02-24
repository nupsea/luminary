/**
 * FloatingToolbar — appears above selected text in the document reader.
 *
 * Listens for mouseup on its container ref, checks window.getSelection(),
 * and positions itself using getBoundingClientRect() on the selection range.
 */

import { useEffect, useRef, useState } from "react"

export type ExplainMode = "plain" | "eli5" | "analogy"

interface FloatingToolbarProps {
  containerRef: React.RefObject<HTMLElement | null>
  onExplain: (text: string, mode: ExplainMode) => void
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

export function FloatingToolbar({ containerRef, onExplain }: FloatingToolbarProps) {
  const [position, setPosition] = useState<Position | null>(null)
  const [selectedText, setSelectedText] = useState("")
  const toolbarRef = useRef<HTMLDivElement>(null)

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
          return
        }

        const range = selection.getRangeAt(0)
        const rect = range.getBoundingClientRect()
        const containerRect = nonNullContainer.getBoundingClientRect()

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
    }

    nonNullContainer.addEventListener("mouseup", handleMouseUp)
    document.addEventListener("mousedown", handleMouseDown)
    return () => {
      nonNullContainer.removeEventListener("mouseup", handleMouseUp)
      document.removeEventListener("mousedown", handleMouseDown)
    }
  }, [containerRef])

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
    </div>
  )
}
