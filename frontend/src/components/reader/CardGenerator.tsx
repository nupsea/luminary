/**
 * CardGenerator -- the "add cards" arm of the Practice face.
 *
 * Generation is a means here, not the surface: the panel leads with the deck
 * that already exists and what is due from it, and this is what fills an empty
 * one. Calls POST /flashcards/generate with scope="section" when a section
 * heading scopes it, otherwise scope="full".
 *
 * Distinct from GenerateFlashcardsDialog, which is note-scoped.
 */

import { useState } from "react"
import { Loader2, Plus } from "lucide-react"

import { ApiError, apiPost } from "@/lib/apiClient"
import { useAppStore } from "@/store"

interface GeneratedCard {
  id: string
}

interface CardGeneratorProps {
  documentId: string
  /** Set when a selection or section scoped the generator. */
  sectionHeading: string | undefined
  /** The selected passage, when one scoped this. */
  context: string
  /** Cards landed in the deck. The panel refetches rather than trusting a list. */
  onGenerated: (count: number) => void
}

export function CardGenerator({
  documentId,
  sectionHeading,
  context,
  onGenerated,
}: CardGeneratorProps) {
  const [count, setCount] = useState(3)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const llmMode = useAppStore((s) => s.llmMode)

  async function handleGenerate() {
    setGenerating(true)
    setError(null)
    try {
      const cards = await apiPost<GeneratedCard[]>("/flashcards/generate", {
        document_id: documentId,
        scope: sectionHeading ? "section" : "full",
        section_heading: sectionHeading ?? null,
        count,
        difficulty: "medium",
        context: context || null,
      })
      onGenerated(cards.length)
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
    <div data-testid="card-generator" className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          Add
          <input
            type="number"
            min={1}
            max={20}
            value={count}
            onChange={(e) =>
              setCount(Math.max(1, Math.min(20, parseInt(e.target.value, 10) || 3)))
            }
            aria-label="How many cards to generate"
            className="w-14 rounded border border-border bg-background px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
          cards
        </label>
        <button
          onClick={() => void handleGenerate()}
          disabled={generating}
          className="flex items-center gap-1.5 rounded border border-border px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-muted disabled:opacity-50"
        >
          {generating ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
          {generating ? "Writing cards..." : "Generate"}
        </button>
      </div>

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
    </div>
  )
}
