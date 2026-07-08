import { useEffect } from "react"

/**
 * Ctrl+S / Cmd+S window-level shortcut. Caller wraps gating in `onSave`.
 */
export function useNoteSaveShortcut(onSave: () => void, enabled: boolean = true) {
  useEffect(() => {
    if (!enabled) return
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault()
        onSave()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onSave, enabled])
}
