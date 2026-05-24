import { useEffect, type ClipboardEvent, type RefObject } from "react"
import { uploadNoteAsset } from "@/lib/noteAssets"

/**
 * Insert markdown at the textarea cursor with surrounding blank lines so the
 * inserted block sits in its own paragraph. Used by mermaid/excalidraw insertions.
 */
export function insertAtTextareaCursor(
  textarea: HTMLTextAreaElement | null,
  value: string,
  setValue: (next: string) => void,
  markdown: string,
) {
  const start = textarea?.selectionStart ?? value.length
  const end = textarea?.selectionEnd ?? value.length
  const prefix = start > 0 && !value.slice(0, start).endsWith("\n") ? "\n\n" : ""
  const suffix = value.slice(end).startsWith("\n") ? "" : "\n\n"
  const insertion = `${prefix}${markdown}${suffix}`
  setValue(value.substring(0, start) + insertion + value.substring(end))
  setTimeout(() => {
    if (!textarea) return
    const newPos = start + insertion.length
    textarea.setSelectionRange(newPos, newPos)
    textarea.focus()
  }, 0)
}

/**
 * Build an onPaste handler that uploads pasted images via uploadNoteAsset
 * and inserts the resulting markdown at the cursor without forcing paragraph
 * breaks. `buildMarkdown` controls the markdown shape (e.g. `|medium` suffix).
 */
export function createImagePasteHandler(
  getTextarea: () => HTMLTextAreaElement | null,
  getValue: () => string,
  setValue: (next: string) => void,
  buildMarkdown: (path: string) => string,
) {
  return async function onPaste(e: ClipboardEvent<HTMLTextAreaElement>) {
    const items = e.clipboardData.items
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.indexOf("image") === -1) continue
      e.preventDefault()
      const file = items[i].getAsFile()
      if (!file) continue
      try {
        const data = await uploadNoteAsset(file)
        const md = buildMarkdown(data.path)
        const ta = getTextarea()
        const value = getValue()
        const start = ta?.selectionStart ?? value.length
        const end = ta?.selectionEnd ?? value.length
        setValue(value.substring(0, start) + md + value.substring(end))
        setTimeout(() => {
          if (!ta) return
          const newPos = start + md.length
          ta.setSelectionRange(newPos, newPos)
          ta.focus()
        }, 0)
      } catch (err) {
        console.error("Paste image failed", err)
      }
    }
  }
}

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

// Re-export RefObject type alias so call sites can type the textarea ref consistently.
export type TextareaRef = RefObject<HTMLTextAreaElement | null>
