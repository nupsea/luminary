import { useCallback, useEffect, useRef, useState } from "react"

export interface ResizablePanelOptions {
  storageKey: string
  defaultWidth: number
  minWidth?: number
  maxWidth?: number
  /** Which edge the drag handle sits on: "left" grows the panel when dragged left. */
  side?: "left" | "right"
}

interface Snapshot {
  width: number
  collapsed: boolean
}

function readSnapshot(key: string, fallback: Snapshot): Snapshot {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    const parsed = JSON.parse(raw) as Partial<Snapshot>
    return {
      width: typeof parsed.width === "number" ? parsed.width : fallback.width,
      collapsed: typeof parsed.collapsed === "boolean" ? parsed.collapsed : fallback.collapsed,
    }
  } catch {
    return fallback
  }
}

function writeSnapshot(key: string, snapshot: Snapshot): void {
  try {
    localStorage.setItem(key, JSON.stringify(snapshot))
  } catch {
    // Private-browsing quota failures must not break the panel.
  }
}

/** A panel the user can drag to resize and collapse, remembered across reloads. */
export function useResizablePanel({
  storageKey,
  defaultWidth,
  minWidth = 180,
  maxWidth = 720,
  side = "left",
}: ResizablePanelOptions) {
  const initial = readSnapshot(storageKey, { width: defaultWidth, collapsed: false })
  const [width, setWidth] = useState(initial.width)
  const [collapsed, setCollapsed] = useState(initial.collapsed)
  const [dragging, setDragging] = useState(false)
  const dragState = useRef<{ startX: number; startWidth: number } | null>(null)

  useEffect(() => {
    writeSnapshot(storageKey, { width, collapsed })
  }, [storageKey, width, collapsed])

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault()
      dragState.current = { startX: e.clientX, startWidth: width }
      setDragging(true)
    },
    [width],
  )

  useEffect(() => {
    if (!dragging) return
    const onMove = (e: PointerEvent) => {
      const state = dragState.current
      if (!state) return
      const delta = side === "left" ? state.startX - e.clientX : e.clientX - state.startX
      setWidth(Math.min(maxWidth, Math.max(minWidth, state.startWidth + delta)))
    }
    const stop = () => {
      dragState.current = null
      setDragging(false)
    }
    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", stop)
    // Suppress text selection while dragging across the document.
    const priorSelect = document.body.style.userSelect
    document.body.style.userSelect = "none"
    return () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", stop)
      document.body.style.userSelect = priorSelect
    }
  }, [dragging, maxWidth, minWidth, side])

  const toggle = useCallback(() => setCollapsed(c => !c), [])

  return { width, collapsed, dragging, toggle, onPointerDown }
}
