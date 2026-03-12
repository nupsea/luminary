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

import { Search, X, Loader2, CheckSquare, Square, CreditCard, Tag as TagIcon } from "lucide-react"
import { useMemo, useState, useEffect } from "react"
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
    return notes.map((n) => ({ id: n.id, content: n.content.slice(0, 150) }))
  } catch {
    return []
  }
}

async function generateNoteFlashcards(
  tag: string | null,
  noteIds: string[] | null,
  count: number,
  difficulty: "easy" | "medium" | "hard",
): Promise<NoteFlashcardItem[]> {
  const res = await fetch(`${API_BASE}/notes/flashcards/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tag: tag || null,
      note_ids: noteIds?.length ? noteIds : null,
      count,
      difficulty,
    }),
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
  const [mode, setMode] = useState<"tag" | "notes">("tag")
  const [selectedTag, setSelectedTag] = useState<string>("")
  const [selectedNoteIds, setSelectedNoteIds] = useState<string[]>([])
  const [availableNotes, setAvailableNotes] = useState<NoteStub[]>([])
  const [noteSearch, setNoteSearch] = useState("")
  const [count, setCount] = useState(5)
  const [difficulty, setDifficulty] = useState<"easy" | "medium" | "hard">("medium")
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

  const filteredNotes = useMemo(() => {
    if (!noteSearch.trim()) return availableNotes
    const q = noteSearch.toLowerCase()
    return availableNotes.filter((n) => n.content.toLowerCase().includes(q))
  }, [availableNotes, noteSearch])

  const canGenerate = (mode === "tag" && !!selectedTag) || (mode === "notes" && selectedNoteIds.length > 0)

  function toggleNoteId(id: string) {
    setSelectedNoteIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  function handleSelectAll() {
    const allVisibleIds = filteredNotes.map((n) => n.id)
    setSelectedNoteIds((prev) => Array.from(new Set([...prev, ...allVisibleIds])))
  }

  function handleClearAll() {
    if (noteSearch) {
      const allVisibleIds = filteredNotes.map((n) => n.id)
      setSelectedNoteIds((prev) => prev.filter((id) => !allVisibleIds.includes(id)))
    } else {
      setSelectedNoteIds([])
    }
  }

  async function handleGenerate() {
    setIsGenerating(true)
    setError(null)
    setSuccess(false)
    try {
      const cards = await generateNoteFlashcards(
        mode === "tag" ? selectedTag : null,
        mode === "notes" ? selectedNoteIds : null,
        count,
        difficulty,
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
    setNoteSearch("")
    setCount(5)
    setDifficulty("medium")
    setError(null)
    setSuccess(false)
    setGeneratedCards([])
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose() }}>
      <DialogContent className="max-w-2xl max-h-[90vh] flex flex-col p-0 overflow-hidden">
        <DialogHeader className="p-6 pb-2">
          <DialogTitle className="text-xl">Generate Flashcards</DialogTitle>
          <DialogDescription>
            Create flashcards from your notes using AI.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          <div className="flex flex-col gap-6">
            {/* Mode Switcher */}
            <div className="flex flex-col gap-2">
              <label className="text-sm font-semibold text-foreground">1. Choose scope</label>
              <div className="grid grid-cols-2 gap-2 rounded-lg bg-muted p-1">
                <button
                  onClick={() => setMode("tag")}
                  className={`flex items-center justify-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-all ${
                    mode === "tag" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <TagIcon size={14} />
                  By Tag
                </button>
                <button
                  onClick={() => setMode("notes")}
                  className={`flex items-center justify-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-all ${
                    mode === "notes" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <CreditCard size={14} />
                  Specific Notes
                </button>
              </div>
            </div>

            {mode === "tag" ? (
              <div className="flex flex-col gap-2 animate-in fade-in slide-in-from-left-2">
                <label className="text-sm font-semibold text-foreground">2. Select a tag</label>
                <select
                  value={selectedTag}
                  onChange={(e) => setSelectedTag(e.target.value)}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                >
                  <option value="">-- Choose a tag --</option>
                  {availableTags.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
                <p className="text-xs text-muted-foreground">All notes with this tag will be used.</p>
              </div>
            ) : (
              <div className="flex flex-col gap-2 animate-in fade-in slide-in-from-right-2">
                <div className="flex items-center justify-between">
                  <label className="text-sm font-semibold text-foreground">2. Select notes</label>
                  <span className="text-xs text-muted-foreground font-medium">
                    {selectedNoteIds.length} selected
                  </span>
                </div>

                <div className="flex flex-col gap-2 rounded-lg border border-border bg-muted/30 p-3">
                  <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <input
                      type="text"
                      placeholder="Search notes..."
                      value={noteSearch}
                      onChange={(e) => setNoteSearch(e.target.value)}
                      className="w-full rounded-md border border-input bg-background pl-9 pr-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                    {noteSearch && (
                      <button
                        onClick={() => setNoteSearch("")}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      >
                        <X size={14} />
                      </button>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleSelectAll}
                      className="flex items-center gap-1.5 rounded bg-background px-2 py-1 text-xs font-medium border border-border hover:bg-accent"
                    >
                      <CheckSquare size={12} />
                      Select {noteSearch ? "visible" : "all"}
                    </button>
                    <button
                      onClick={handleClearAll}
                      className="flex items-center gap-1.5 rounded bg-background px-2 py-1 text-xs font-medium border border-border hover:bg-accent"
                    >
                      <Square size={12} />
                      Clear {noteSearch ? "visible" : "all"}
                    </button>
                  </div>

                  <div className="mt-1 max-h-60 overflow-y-auto rounded-md border border-border bg-background shadow-sm">
                    {filteredNotes.length > 0 ? (
                      filteredNotes.map((note) => (
                        <label
                          key={note.id}
                          className={`flex cursor-pointer items-start gap-3 px-3 py-2.5 text-sm transition-colors hover:bg-accent/50 ${
                            selectedNoteIds.includes(note.id) ? "bg-primary/5" : ""
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={selectedNoteIds.includes(note.id)}
                            onChange={() => toggleNoteId(note.id)}
                            className="mt-0.5 h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                          />
                          <span className="line-clamp-3 text-foreground leading-relaxed">{note.content}</span>
                        </label>
                      ))
                    ) : (
                      <div className="py-8 text-center text-sm text-muted-foreground">
                        {availableNotes.length === 0 ? "No notes found." : "No matching notes."}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Count & Action */}
            <div className="flex flex-col gap-4 border-t border-border pt-6">
              <div className="flex items-center justify-between">
                <div className="flex flex-col gap-1">
                  <label className="text-sm font-semibold text-foreground">3. Difficulty & Count</label>
                  <p className="text-xs text-muted-foreground">Adjust generation settings.</p>
                </div>
                <div className="flex items-center gap-2">
                  <select
                    value={difficulty}
                    onChange={(e) => setDifficulty(e.target.value as "easy" | "medium" | "hard")}
                    className="w-28 rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    <option value="easy">Easy</option>
                    <option value="medium">Medium</option>
                    <option value="hard">Hard</option>
                  </select>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={count}
                    onChange={(e) => setCount(Math.max(1, Math.min(20, Number(e.target.value))))}
                    className="w-16 rounded-md border border-input bg-background px-3 py-2 text-sm text-center focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>

              <div className="flex justify-center">
                <button
                  onClick={() => { void handleGenerate() }}
                  disabled={!canGenerate || isGenerating}
                  className="flex h-10 items-center gap-2 rounded-md bg-primary px-8 py-2 text-sm font-semibold text-primary-foreground shadow transition-colors hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isGenerating ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Generating...
                    </>
                  ) : (
                    "Generate Cards"
                  )}
                </button>
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="rounded-md border border-red-200 bg-red-50 p-4">
                <p className="text-sm font-medium text-red-800">{error}</p>
              </div>
            )}

            {/* Success Results */}
            {success && generatedCards.length > 0 && (
              <div className="flex flex-col gap-4 border-t border-border pt-6 animate-in fade-in slide-in-from-top-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-bold text-foreground">Generated Flashcards</h3>
                  <span className="rounded-full bg-green-100 px-3 py-1 text-xs font-bold text-green-700">
                    {generatedCards.length} Cards
                  </span>
                </div>
                <div className="flex flex-col gap-3">
                  {generatedCards.map((card, idx) => (
                    <div key={card.id || idx} className="rounded-lg border border-border bg-card p-4 shadow-sm">
                      <p className="text-xs font-bold text-muted-foreground uppercase mb-2">Question</p>
                      <p className="text-sm font-medium text-foreground mb-3">{card.question}</p>
                      <div className="border-t border-border pt-3">
                        <p className="text-xs font-bold text-muted-foreground uppercase mb-2">Answer</p>
                        <p className="text-sm text-foreground/80">{card.answer}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {success && generatedCards.length === 0 && (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-center">
                <p className="text-sm text-amber-800 italic">No flashcards were generated. Try broadening your selection.</p>
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="border-t border-border p-4 bg-muted/10">
          <button
            onClick={handleClose}
            className="rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent transition-colors"
          >
            {success ? "Done" : "Cancel"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

