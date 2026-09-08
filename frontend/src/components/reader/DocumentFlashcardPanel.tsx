/**
 * DocumentFlashcardPanel -- the Practice face of the reader's docked panel.
 *
 * Distinct from GenerateFlashcardsDialog (which is note-scoped).
 * Calls POST /flashcards/generate with scope="section" when sectionHeading is
 * provided, otherwise scope="full".
 */

import { useState } from "react"
import { Loader2, X } from "lucide-react"
import { ApiError, apiPost } from "@/lib/apiClient"
import { useAppStore } from "@/store"

interface FlashcardResult {
  id: string
  question: string
  answer: string
}

interface DocumentFlashcardPanelProps {
  documentId: string
  /** Set when a selection scoped this generator; clearing it returns to the document. */
  sectionHeading: string | undefined
  context: string
  onClearScope: () => void
}

export function DocumentFlashcardPanel({
  documentId,
  sectionHeading,
  context,
  onClearScope,
}: DocumentFlashcardPanelProps) {
  const [count, setCount] = useState(3)
  const [generating, setGenerating] = useState(false)
  const [generated, setGenerated] = useState<FlashcardResult[]>([])
  const [error, setError] = useState<string | null>(null)
  const llmMode = useAppStore((s) => s.llmMode)

  const scoped = Boolean(context || sectionHeading)

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
        setError(
          llmMode === "private"
            ? "Generation failed. Is Ollama running?"
            : "Generation failed. Check your internet connection or settings."
        )
      }
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div data-testid="docked-practice" className="flex h-full min-h-0 flex-col">
      <div className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">Generate flashcards from</p>
          <p data-testid="practice-scope" className="line-clamp-2 text-sm font-medium text-foreground">
            {context
              ? `Selected text (${context.length} chars)`
              : sectionHeading
                ? `Section: ${sectionHeading}`
                : "This document"}
          </p>
        </div>
        {scoped && (
          <button
            onClick={() => { setGenerated([]); setError(null); onClearScope() }}
            aria-label="Clear the selected scope"
            title="Use the whole document"
            className="shrink-0 text-muted-foreground hover:text-foreground"
          >
            <X size={16} />
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-4">
        <div className="flex items-center gap-3">
          <label className="text-xs text-foreground">
            Count:
            <input
              type="number"
              min={1}
              max={20}
              value={count}
              onChange={(e) =>
                setCount(Math.max(1, Math.min(20, parseInt(e.target.value, 10) || 3)))
              }
              className="ml-2 w-16 rounded border border-border bg-background px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </label>
          <button
            onClick={() => void handleGenerate()}
            disabled={generating}
            className="flex items-center gap-1.5 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {generating && <Loader2 size={13} className="animate-spin" />}
            Generate
          </button>
        </div>

        {error && (
          <div className="mt-3 rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {error}
            <button
              onClick={() => void handleGenerate()}
              className="ml-2 underline hover:no-underline"
            >
              Retry
            </button>
          </div>
        )}

        {generating ? (
          <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 size={13} className="animate-spin" />
            Generating flashcards...
          </div>
        ) : generated.length > 0 ? (
          <ul className="mt-4 space-y-2">
            {generated.map((card, i) => (
              <li key={card.id ?? i} className="rounded-md border border-border p-2 text-xs">
                <p className="font-medium text-foreground">{card.question}</p>
                <p className="mt-1 text-muted-foreground">{card.answer}</p>
              </li>
            ))}
          </ul>
        ) : !error ? (
          <p className="mt-4 text-xs text-muted-foreground">
            No cards yet. Generate from this document, or select a passage first to scope them
            to it.
          </p>
        ) : null}
      </div>
    </div>
  )
}
