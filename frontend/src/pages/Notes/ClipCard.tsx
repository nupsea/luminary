// ClipCard -- single highlighted-clip entry in the Reading Journal
// tab. Shows the blockquoted selection, attribution (doc + section),
// an editable user note (autosave on blur), and a row of actions:
// navigate to source, convert to note, create flashcard, delete.

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"
import { useRef, useState } from "react"

import { relativeDate } from "@/components/library/utils"

import { deleteClip, patchClipNote } from "./api"
import type { Clip } from "./types"

interface ClipCardProps {
  clip: Clip
  docTitle: string
  onDeleted: () => void
  onConvertToNote: (clip: Clip) => void
  onCreateFlashcard: (clip: Clip) => void
  navigate: (url: string) => void
}

export function ClipCard({
  clip,
  docTitle,
  onDeleted,
  onConvertToNote,
  onCreateFlashcard,
  navigate,
}: ClipCardProps) {
  const [confirming, setConfirming] = useState(false)
  const [noteText, setNoteText] = useState(clip.user_note)
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle")
  const abortRef = useRef<AbortController | null>(null)
  const qc = useQueryClient()

  const deleteMut = useMutation({
    mutationFn: () => deleteClip(clip.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["clips"] })
      onDeleted()
    },
  })

  async function handleNoteBlur() {
    if (noteText === clip.user_note) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setSaveStatus("saving")
    try {
      await patchClipNote(clip.id, noteText)
      setSaveStatus("saved")
      void qc.invalidateQueries({ queryKey: ["clips"] })
      setTimeout(() => setSaveStatus("idle"), 2000)
    } catch {
      if (!controller.signal.aborted) setSaveStatus("error")
    }
  }

  const attribution = [docTitle, clip.section_heading].filter(Boolean).join(" — ")

  const sourceUrl = clip.section_id
    ? `/?doc=${clip.document_id}&section_id=${clip.section_id}`
    : clip.pdf_page_number
      ? `/?doc=${clip.document_id}&page=${clip.pdf_page_number}`
      : `/?doc=${clip.document_id}`

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3">
      {/* Blockquote */}
      <blockquote className="border-l-4 border-l-blue-400 pl-3 text-sm italic text-foreground">
        {clip.selected_text}
      </blockquote>

      {/* Attribution */}
      <p className="text-xs text-muted-foreground">{attribution}</p>

      {/* User note */}
      <div className="relative">
        <textarea
          value={noteText}
          onChange={(e) => setNoteText(e.target.value)}
          onBlur={() => void handleNoteBlur()}
          placeholder="Add your note..."
          className="w-full resize-none rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          rows={2}
        />
        {saveStatus === "saving" && (
          <span className="absolute bottom-1 right-2 text-xs text-muted-foreground">
            Saving...
          </span>
        )}
        {saveStatus === "saved" && (
          <span className="absolute bottom-1 right-2 text-xs text-green-600">Saved</span>
        )}
        {saveStatus === "error" && (
          <span className="absolute bottom-1 right-2 text-xs text-red-600">Save failed</span>
        )}
      </div>

      {/* Actions row */}
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <button
          onClick={() => navigate(sourceUrl)}
          className="rounded border border-border px-2 py-0.5 text-muted-foreground hover:text-foreground hover:bg-accent"
        >
          Navigate to source
        </button>
        <button
          onClick={() => onConvertToNote(clip)}
          className="rounded border border-border px-2 py-0.5 text-muted-foreground hover:text-foreground hover:bg-accent"
        >
          Convert to Note
        </button>
        <button
          onClick={() => onCreateFlashcard(clip)}
          className="rounded border border-border px-2 py-0.5 text-muted-foreground hover:text-foreground hover:bg-accent"
        >
          Create Flashcard
        </button>
        <div className="flex-1" />
        <span className="text-muted-foreground">{relativeDate(clip.created_at)}</span>
        {confirming ? (
          <>
            <button
              onClick={() => deleteMut.mutate()}
              disabled={deleteMut.isPending}
              className="rounded bg-destructive px-2 py-0.5 text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
            >
              Yes
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="rounded border border-border px-2 py-0.5 hover:bg-accent"
            >
              No
            </button>
          </>
        ) : (
          <button
            onClick={() => setConfirming(true)}
            className="rounded p-0.5 text-muted-foreground hover:text-destructive hover:bg-accent"
            title="Delete clip"
          >
            <Trash2 size={12} />
          </button>
        )}
      </div>
    </div>
  )
}
