/**
 * DocumentFlashcardDialog -- generate flashcards scoped to selected text context (S147).
 *
 * Distinct from GenerateFlashcardsDialog (which is note-scoped).
 * Calls POST /flashcards/generate with scope="section" when sectionHeading is provided,
 * otherwise scope="full".
 */

import { useState } from "react"
import { Loader2 } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ApiError, apiPost } from "@/lib/apiClient"

interface FlashcardResult {
  id: string
  question: string
  answer: string
}

interface DocumentFlashcardDialogProps {
  open: boolean
  documentId: string
  sectionId: string | undefined
  sectionHeading: string | undefined
  context: string
  onClose: () => void
}

export function DocumentFlashcardDialog({
  open,
  documentId,
  sectionId: _sectionId,
  sectionHeading,
  context,
  onClose,
}: DocumentFlashcardDialogProps) {
  const [count, setCount] = useState(3)
  const [generating, setGenerating] = useState(false)
  const [generated, setGenerated] = useState<FlashcardResult[]>([])
  const [error, setError] = useState<string | null>(null)

  async function handleGenerate() {
    setGenerating(true)
    setError(null)
    setGenerated([])
    try {
      const cards = await apiPost<FlashcardResult[]>("/flashcards/generate", {
        document_id: documentId,
        scope: sectionHeading ? "section" : "full",
        section_heading: sectionHeading ?? null,
        count,
        difficulty: "medium",
        context: context || null,
      })
      setGenerated(cards)
    } catch (err) {
      if (err instanceof ApiError) {
        let detail = `Generation failed (HTTP ${err.status})`
        try {
          const body = JSON.parse(err.body) as { detail?: string }
          if (body.detail) detail = body.detail
        } catch {
          // body wasn't JSON
        }
        setError(detail)
      } else {
        setError("Generation failed. Is Ollama running?")
      }
    } finally {
      setGenerating(false)
    }
  }

  function handleClose() {
    setGenerated([])
    setError(null)
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) handleClose() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Generate Flashcards</DialogTitle>
          <DialogDescription>
            {context
              ? `Selected text (${context.length} chars)`
              : sectionHeading
                ? `Section: ${sectionHeading}`
                : "Full document"}
          </DialogDescription>
        </DialogHeader>

        {generated.length === 0 && !generating && (
          <div className="flex items-center gap-3">
            <label className="text-sm text-foreground">
              Count:
              <input
                type="number"
                min={1}
                max={20}
                value={count}
                onChange={(e) =>
                  setCount(Math.max(1, Math.min(20, parseInt(e.target.value, 10) || 3)))
                }
                className="ml-2 w-16 rounded border border-border bg-background px-2 py-1 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </label>
          </div>
        )}

        {error && (
          <div className="rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {error}
            <button
              onClick={() => void handleGenerate()}
              className="ml-2 underline hover:no-underline"
            >
              Retry
            </button>
          </div>
        )}

        {generating && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 size={14} className="animate-spin" />
            Generating flashcards...
          </div>
        )}

        {generated.length > 0 && (
          <ul className="max-h-64 space-y-2 overflow-auto">
            {generated.map((card, i) => (
              <li key={card.id ?? i} className="rounded-md border border-border p-2 text-xs">
                <p className="font-medium text-foreground">{card.question}</p>
                <p className="mt-1 text-muted-foreground">{card.answer}</p>
              </li>
            ))}
          </ul>
        )}

        <DialogFooter>
          {generated.length > 0 ? (
            <button
              onClick={handleClose}
              className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Done
            </button>
          ) : (
            <>
              <button
                onClick={handleClose}
                className="rounded border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
              <button
                onClick={() => void handleGenerate()}
                disabled={generating}
                className="flex items-center gap-1.5 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {generating && <Loader2 size={14} className="animate-spin" />}
                Generate
              </button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
