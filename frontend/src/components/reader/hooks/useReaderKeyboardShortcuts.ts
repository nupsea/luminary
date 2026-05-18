import { useEffect } from "react"

interface UseReaderKeyboardShortcutsOpts {
  onBack: () => void
  onOpenSearch: () => void
  onCloseSearch: () => void
  searchOpen: boolean
}

// Wires the three reader-wide keyboard shortcuts:
//   Cmd/Ctrl+[  -- back via the in-document navigation stack
//   Cmd/Ctrl+F  -- open the in-document search bar
//   Escape      -- close the search bar (only while open)
export function useReaderKeyboardShortcuts({
  onBack,
  onOpenSearch,
  onCloseSearch,
  searchOpen,
}: UseReaderKeyboardShortcutsOpts) {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey)) return
      if (e.key === "[") {
        e.preventDefault()
        onBack()
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onBack])

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault()
        onOpenSearch()
      }
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [onOpenSearch])

  useEffect(() => {
    if (!searchOpen) return
    function handler(e: KeyboardEvent) {
      if (e.key === "Escape") onCloseSearch()
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [searchOpen, onCloseSearch])
}
