/**
 * AnnotationPopover — color swatch + optional note popover.
 *
 * Rendered by DocumentReader after the user clicks "Highlight" in FloatingToolbar.
 * Positioned absolutely within the section list container.
 */

import { useState } from "react"
import type { HighlightInfo } from "@/components/FloatingToolbar"
import type { AnnotationItem } from "./types"

import { apiPost } from "@/lib/apiClient"

const COLORS: { id: "yellow" | "green" | "blue" | "pink"; bg: string; label: string }[] = [
  { id: "yellow", bg: "bg-yellow-300", label: "Yellow" },
  { id: "green", bg: "bg-green-300", label: "Green" },
  { id: "blue", bg: "bg-blue-300", label: "Blue" },
  { id: "pink", bg: "bg-pink-300", label: "Pink" },
]

interface AnnotationPopoverProps {
  info: HighlightInfo
  documentId: string
  position: { top: number; left: number }
  onSaved: (annotation: AnnotationItem) => void
  onCancel: () => void
}

export function AnnotationPopover({
  info,
  documentId,
  position,
  onSaved,
  onCancel,
}: AnnotationPopoverProps) {
  const [selectedColor, setSelectedColor] = useState<"yellow" | "green" | "blue" | "pink">(
    "yellow",
  )
  const [noteText, setNoteText] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const annotation = await apiPost<AnnotationItem>("/annotations", {
        document_id: documentId,
        section_id: info.sectionId,
        chunk_id: null,
        selected_text: info.text,
        start_offset: info.startOffset,
        end_offset: info.endOffset,
        color: selectedColor,
        note_text: noteText.trim() || null,
      })
      onSaved(annotation)
    } catch {
      setError("Failed to save highlight. Please try again.")
      setSaving(false)
    }
  }

  return (
    <div
      className="absolute z-50 w-56 rounded-lg border border-border bg-popover p-3 shadow-lg"
      style={{ top: position.top, left: position.left }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <p className="mb-2 truncate text-xs text-muted-foreground" title={info.text}>
        &ldquo;{info.text.slice(0, 40)}{info.text.length > 40 ? "..." : ""}&rdquo;
      </p>

      {/* Color swatches */}
      <div className="mb-2 flex gap-2">
        {COLORS.map((c) => (
          <button
            key={c.id}
            title={c.label}
            onClick={() => setSelectedColor(c.id)}
            className={`h-7 w-7 rounded-full border-2 transition-transform ${c.bg} ${
              selectedColor === c.id
                ? "border-foreground scale-110"
                : "border-transparent hover:scale-105"
            }`}
          />
        ))}
      </div>

      {/* Optional note */}
      <textarea
        value={noteText}
        onChange={(e) => setNoteText(e.target.value)}
        placeholder="Add a note (optional)"
        disabled={saving}
        rows={2}
        className="mb-2 w-full resize-none rounded border border-border bg-background px-2 py-1 text-xs outline-none focus:border-primary disabled:opacity-50"
      />

      {error && <p className="mb-1 text-xs text-destructive">{error}</p>}

      <div className="flex justify-end gap-2">
        <button
          onClick={onCancel}
          disabled={saving}
          className="rounded border border-border px-2.5 py-1 text-xs hover:bg-accent disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          onClick={() => void handleSave()}
          disabled={saving}
          className="rounded bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  )
}
