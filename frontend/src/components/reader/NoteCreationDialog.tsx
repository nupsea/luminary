/**
 * NoteCreationDialog -- modal for creating a note pre-filled with selected text (S147).
 *
 * Distinct from NoteEditorDialog (which edits existing notes with tag-suggest flow).
 * Pre-fills a blockquote of selectedText + attribution line, then POST /notes on save.
 */

import { useEffect, useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import type { SourceRef } from "./SelectionActionBar"
import { API_BASE } from "@/lib/config"

interface NoteCreationDialogProps {
  open: boolean
  selectedText: string
  sourceRef: SourceRef | null
  sectionHeading?: string
  onClose: () => void
  onSaved: () => void
}

export function NoteCreationDialog({
  open,
  selectedText,
  sourceRef,
  sectionHeading,
  onClose,
  onSaved,
}: NoteCreationDialogProps) {
  const [content, setContent] = useState("")
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Pre-fill content whenever the dialog opens with new text
  useEffect(() => {
    if (open && selectedText) {
      const parts = [sourceRef?.documentTitle, sectionHeading].filter(Boolean)
      const attribution = parts.length > 0 ? parts.join(", ") : ""
      setContent(`> "${selectedText}"\n>\n> -- ${attribution}`)
      setSaveError(null)
    }
  }, [open, selectedText, sourceRef, sectionHeading])

  async function handleSave() {
    if (!content.trim() || !sourceRef) return
    setSaving(true)
    setSaveError(null)
    try {
      const res = await fetch(`${API_BASE}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: sourceRef.documentId,
          section_id: sourceRef.sectionId ?? null,
          content,
          tags: [],
          group_name: null,
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      onSaved()
      onClose()
    } catch {
      setSaveError("Failed to save note. Please try again.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Add to Note</DialogTitle>
          <DialogDescription>
            Edit the pre-filled content before saving.
          </DialogDescription>
        </DialogHeader>
        {saveError && (
          <p className="text-xs text-destructive">{saveError}</p>
        )}
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          className="min-h-[120px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 font-mono text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <DialogFooter>
          <button
            onClick={onClose}
            className="rounded border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
          >
            Cancel
          </button>
          <button
            onClick={() => void handleSave()}
            disabled={saving || !content.trim()}
            className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
