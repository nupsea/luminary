/**
 * CardGenerator -- the "add cards" and "start over" arm of the Practice face.
 *
 * Generation is a means here, not the surface: the panel leads with the deck
 * that already exists and what is due from it, and this is what fills or
 * replaces one. Calls POST /flashcards/generate with scope="section" when a
 * section heading scopes it, otherwise scope="full".
 *
 * Start over is POST /flashcards/regenerate, which is one request rather than a
 * delete-then-generate pair on purpose: the replacement is written while the old
 * deck is still in the table, so the near-duplicate filter has something to
 * compare against and a run that produces nothing leaves the learner their
 * cards. It is scoped to whatever scopes the panel -- replacing a chapter must
 * not take the rest of the book's deck with it -- and it is confirmed first,
 * because it deletes cards the learner may have practised for weeks, and the
 * runs those cards leave empty.
 *
 * Distinct from GenerateFlashcardsDialog, which is note-scoped.
 */

import { useState } from "react"
import { Loader2, Plus, RotateCcw } from "lucide-react"

import { ApiError, apiPost } from "@/lib/apiClient"
import { shortModelLabel } from "@/lib/chatSettingsUtils"
import type { Flashcard } from "@/lib/studyApi"
import { useAppStore } from "@/store"

interface RegenerateResponse {
  cards: Flashcard[]
  requested: number
  delivered: number
  replaced: number
  kept_previous: boolean
  sessions_removed: number
}

interface CardGeneratorProps {
  documentId: string
  /** Set when a selection or section scoped the generator. */
  sectionId: string | undefined
  sectionHeading: string | undefined
  /** The selected passage, when one scoped this. */
  context: string
  /** Per-request model override; "" follows Settings. */
  model: string
  /**
   * Every passage in this scope already has a question, so Generate can only
   * produce near-duplicates the filter will drop. Replacing is still offered:
   * it reads the same material with the deck removed from the comparison, which
   * is a different request and the one that makes sense here.
   */
  exhausted: boolean
  /** Cards landed in the deck. The panel refetches rather than trusting a list. */
  onGenerated: (cards: Flashcard[]) => void
  /** The scope's deck was replaced. Carries what the run must be rebuilt from. */
  onReplaced: (result: {
    cards: Flashcard[]
    replaced: number
    sessionsRemoved: number
  }) => void
}

export function CardGenerator({
  documentId,
  sectionId,
  sectionHeading,
  context,
  model,
  exhausted,
  onGenerated,
  onReplaced,
}: CardGeneratorProps) {
  const [count, setCount] = useState(3)
  const [generating, setGenerating] = useState(false)
  const [replacing, setReplacing] = useState(false)
  const [confirmingReplace, setConfirmingReplace] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const llmMode = useAppStore((s) => s.llmMode)

  const scopeName = sectionHeading ? "this section" : "this document"
  const busy = generating || replacing

  function describe(err: unknown, fallback: string): string {
    if (err instanceof ApiError) {
      try {
        const body = JSON.parse(err.body) as { detail?: string }
        if (body.detail) return body.detail
      } catch {
        // body wasn't JSON
      }
      return `${fallback} (HTTP ${err.status})`
    }
    return llmMode === "private"
      ? `${fallback} Is Ollama running?`
      : `${fallback} Check your internet connection or settings.`
  }

  async function handleGenerate() {
    setGenerating(true)
    setError(null)
    try {
      const cards = await apiPost<Flashcard[]>("/flashcards/generate", {
        document_id: documentId,
        scope: sectionHeading ? "section" : "full",
        section_heading: sectionHeading ?? null,
        count,
        difficulty: "medium",
        context: context || null,
        avoid_used_material: true,
        model: model || null,
      })
      onGenerated(cards)
    } catch (err) {
      setError(describe(err, "Generation failed."))
    } finally {
      setGenerating(false)
    }
  }

  async function handleReplace() {
    setConfirmingReplace(false)
    setReplacing(true)
    setError(null)
    try {
      const result = await apiPost<RegenerateResponse>("/flashcards/regenerate", {
        document_id: documentId,
        count,
        difficulty: "medium",
        section_id: sectionId ?? null,
        section_heading: sectionHeading ?? null,
        model: model || null,
      })
      if (result.kept_previous) {
        // The endpoint deletes last and only on success, so nothing was lost.
        setError("Nothing usable came back, so your existing cards were kept.")
        return
      }
      onReplaced({
        cards: result.cards,
        replaced: result.replaced,
        sessionsRemoved: result.sessions_removed,
      })
    } catch (err) {
      setError(describe(err, "Could not replace these cards."))
    } finally {
      setReplacing(false)
    }
  }

  return (
    <div data-testid="card-generator" className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          {exhausted ? "Replace with" : "Add"}
          <input
            type="number"
            min={1}
            max={20}
            value={count}
            onChange={(e) =>
              setCount(Math.max(1, Math.min(20, parseInt(e.target.value, 10) || 3)))
            }
            aria-label="How many cards to generate"
            className="w-16 rounded-lg border border-border bg-background px-2.5 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
          cards
        </label>
        {!exhausted && (
          <button
            onClick={() => void handleGenerate()}
            disabled={busy}
            className="flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
          >
            {generating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            {generating ? "Writing cards..." : "Generate"}
          </button>
        )}
        <button
          data-testid="regenerate-cards"
          onClick={() => setConfirmingReplace(true)}
          disabled={busy}
          className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
        >
          {replacing ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <RotateCcw size={14} />
          )}
          {replacing ? "Writing a new set..." : "Start over"}
        </button>
      </div>

      {exhausted && !confirmingReplace && (
        <p data-testid="material-exhausted" className="text-sm text-muted-foreground">
          Every passage in {scopeName} already has a question, so there is nothing
          new to add. Start over to write a fresh set from the same material --
          a different model will ask different questions of it.
        </p>
      )}

      {confirmingReplace && (
        <div
          data-testid="regenerate-confirm"
          className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 dark:border-amber-800 dark:bg-amber-950/30"
        >
          <p className="text-sm font-medium text-amber-900 dark:text-amber-200">
            Replace every card on {scopeName}?
          </p>
          <p className="mt-1 text-sm text-amber-800 dark:text-amber-300">
            The current cards are deleted and {count} fresh questions are written
            from the start{model ? ` by ${shortModelLabel(model)}` : ""}. Any run
            left with no cards to practise goes with them -- your progress record
            (streak, reviews, accuracy) is kept. This cannot be undone.
          </p>
          <div className="mt-3 flex items-center gap-2">
            <button
              data-testid="regenerate-confirm-yes"
              onClick={() => void handleReplace()}
              className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-amber-700"
            >
              Replace them
            </button>
            <button
              onClick={() => setConfirmingReplace(false)}
              className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
            >
              Keep them
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}
    </div>
  )
}
