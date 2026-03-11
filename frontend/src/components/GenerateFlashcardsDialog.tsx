/**
 * GenerateFlashcardsDialog -- generate flashcards from notes scoped by tag or note IDs.
 *
 * Props:
 *   open        — controls dialog visibility
 *   onClose     — called when dialog should close
 *   availableTags   — list of tag names from GET /notes/groups
 *
 * Scope: user selects EITHER a tag (all notes with that tag) OR specific notes from a
 * multi-select list. Generate button is disabled until tag or at least one note is chosen.
 * 503 Ollama error is shown as 'Ollama is unavailable. Start it with: ollama serve'.
 */

import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

const API_BASE = "http://localhost:8000"

interface NoteStub {
  id: string
  content: string
}

interface NoteFlashcardItem {
  id: string
  question: string
  answer: string
  source_excerpt: string
  source: string
}

interface GenerateFlashcardsDialogProps {
  open: boolean
  onClose: () => void
  availableTags: string[]
}

async function fetchNoteStubs(): Promise<NoteStub[]> {
  try {
    const res = await fetch(`${API_BASE}/notes`)
    if (!res.ok) return []
    const notes = (await res.json()) as { id: string; content: string }[]
    return notes.map((n) => ({ id: n.id, content: n.content.slice(0, 80) }))
  } catch {
    return []
  }
}

async function generateNoteFlashcards(
  tag: string | null,
  noteIds: string[] | null,
  count: number,
): Promise<NoteFlashcardItem[]> {
  const res = await fetch(`${API_BASE}/notes/flashcards/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tag: tag || null, note_ids: noteIds?.length ? noteIds : null, count }),
  })
  if (res.status === 503) {
    throw new Error("Ollama is unavailable. Start it with: ollama serve")
  }
  if (!res.ok) {
    const detail = ((await res.json()) as { detail?: string }).detail ?? `HTTP ${res.status}`
    throw new Error(detail)
  }
  return res.json() as Promise<NoteFlashcardItem[]>
}

export function GenerateFlashcardsDialog({
  open,
  onClose,
  availableTags,
}: GenerateFlashcardsDialogProps) {
  const [selectedTag, setSelectedTag] = useState<string>("")
  const [selectedNoteIds, setSelectedNoteIds] = useState<string[]>([])
  const [availableNotes, setAvailableNotes] = useState<NoteStub[]>([])
  const [count, setCount] = useState(5)
  const [isGenerating, setIsGenerating] = useState(false)
  const [generatedCards, setGeneratedCards] = useState<NoteFlashcardItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  // Fetch notes when dialog opens
  useEffect(() => {
    if (open) {
      void fetchNoteStubs().then(setAvailableNotes)
    }
  }, [open])

  const canGenerate = !!selectedTag || selectedNoteIds.length > 0

  function toggleNoteId(id: string) {
    setSelectedNoteIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  async function handleGenerate() {
    setIsGenerating(true)
    setError(null)
    setSuccess(false)
    try {
      const cards = await generateNoteFlashcards(
        selectedTag || null,
        selectedNoteIds.length > 0 ? selectedNoteIds : null,
        count,
      )
      setGeneratedCards(cards)
      setSuccess(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed")
    } finally {
      setIsGenerating(false)
    }
  }

  function handleClose() {
    setSelectedTag("")
    setSelectedNoteIds([])
    setCount(5)
    setError(null)
    setSuccess(false)
    setGeneratedCards([])
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Generate Flashcards from Notes</DialogTitle>
          <DialogDescription>
            Select a tag or specific notes to generate flashcards using AI.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          {/* Tag selector */}
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium">Filter by tag (all notes with this tag)</label>
            <select
              value={selectedTag}
              onChange={(e) => { setSelectedTag(e.target.value); setSelectedNoteIds([]) }}
              className="rounded border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">-- No tag filter --</option>
              {availableTags.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>

          {/* Note multi-select */}
          {availableNotes.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium">
                Or select specific notes
                {selectedNoteIds.length > 0 && (
                  <span className="ml-2 text-xs text-muted-foreground">
                    ({selectedNoteIds.length} selected)
                  </span>
                )}
              </label>
              <div className="max-h-40 overflow-y-auto rounded border border-border bg-background">
                {availableNotes.map((note) => (
                  <label
                    key={note.id}
                    className="flex cursor-pointer items-start gap-2 px-3 py-2 text-sm hover:bg-accent/50"
                  >
                    <input
                      type="checkbox"
                      checked={selectedNoteIds.includes(note.id)}
                      onChange={() => { setSelectedTag(""); toggleNoteId(note.id) }}
                      className="mt-0.5 shrink-0"
                    />
                    <span className="line-clamp-2 text-foreground">{note.content}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {/* Count */}
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium">Number of cards</label>
            <input
              type="number"
              min={1}
              max={20}
              value={count}
              onChange={(e) => setCount(Math.max(1, Math.min(20, Number(e.target.value))))}
              className="w-24 rounded border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Generate button */}
          <button
            onClick={() => { void handleGenerate() }}
            disabled={!canGenerate || isGenerating}
            className="flex items-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50 disabled:cursor-not-allowed hover:bg-primary/90 transition-colors w-fit"
          >
            {isGenerating && <Loader2 className="h-4 w-4 animate-spin" />}
            {isGenerating ? "Generating..." : "Generate"}
          </button>

          {/* Error */}
          {error && (
            <p className="text-sm text-red-600 bg-red-50 rounded px-3 py-2 border border-red-200">
              {error}
            </p>
          )}

          {/* Success */}
          {success && generatedCards.length > 0 && (
            <div className="flex flex-col gap-2">
              <p className="text-sm text-green-700">
                Generated {generatedCards.length} flashcard{generatedCards.length !== 1 ? "s" : ""}.
              </p>
              <div className="max-h-60 overflow-y-auto flex flex-col gap-2">
                {generatedCards.map((card) => (
                  <div key={card.id} className="rounded border border-border bg-muted p-3 text-sm">
                    <p className="font-medium">{card.question}</p>
                    <p className="text-muted-foreground mt-1">{card.answer}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {success && generatedCards.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No flashcards generated. Try selecting a different tag or notes.
            </p>
          )}
        </div>

        <DialogFooter>
          <button
            onClick={handleClose}
            className="rounded border border-border px-4 py-2 text-sm hover:bg-muted transition-colors"
          >
            {success ? "Done" : "Cancel"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
