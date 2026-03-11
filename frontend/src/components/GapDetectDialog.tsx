/**
 * GapDetectDialog -- compare user notes with a book and surface gaps.
 *
 * Props:
 *   open     — controls visibility
 *   onClose  — called to close
 *
 * Flow:
 *   1. User selects a book from document dropdown (GET /documents)
 *   2. User selects notes from a checkbox list (GET /notes)
 *   3. User clicks Analyze -- POST /notes/gap-detect
 *   4. Gaps and covered concepts displayed in two sections
 *
 * States: loading (skeleton), error (amber), empty (placeholder).
 * 503 shown as 'Ollama is unavailable. Start it with: ollama serve'.
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

interface DocumentItem {
  id: string
  title: string
}

interface NoteStub {
  id: string
  content: string
}

interface GapDetectResult {
  gaps: string[]
  covered: string[]
  query_used: string
}

async function fetchDocuments(): Promise<DocumentItem[]> {
  try {
    const res = await fetch(`${API_BASE}/documents?page_size=100`)
    if (!res.ok) return []
    const data = (await res.json()) as { items?: DocumentItem[] } | DocumentItem[]
    return Array.isArray(data) ? data : (data.items ?? [])
  } catch {
    return []
  }
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

async function runGapDetect(
  noteIds: string[],
  documentId: string,
): Promise<GapDetectResult> {
  const res = await fetch(`${API_BASE}/notes/gap-detect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note_ids: noteIds, document_id: documentId }),
  })
  if (res.status === 503) {
    throw new Error("Ollama is unavailable. Start it with: ollama serve")
  }
  if (!res.ok) {
    const detail = ((await res.json()) as { detail?: string }).detail ?? `HTTP ${res.status}`
    throw new Error(detail)
  }
  return res.json() as Promise<GapDetectResult>
}

interface GapDetectDialogProps {
  open: boolean
  onClose: () => void
}

export function GapDetectDialog({ open, onClose }: GapDetectDialogProps) {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [notes, setNotes] = useState<NoteStub[]>([])
  const [selectedDocId, setSelectedDocId] = useState("")
  const [selectedNoteIds, setSelectedNoteIds] = useState<string[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isFetching, setIsFetching] = useState(false)
  const [result, setResult] = useState<GapDetectResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setIsFetching(true)
      void Promise.all([fetchDocuments(), fetchNoteStubs()]).then(([docs, noteList]) => {
        setDocuments(docs)
        setNotes(noteList)
        setIsFetching(false)
      })
    }
  }, [open])

  const canAnalyze = !!selectedDocId && selectedNoteIds.length > 0

  function toggleNoteId(id: string) {
    setSelectedNoteIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  async function handleAnalyze() {
    setIsLoading(true)
    setError(null)
    setResult(null)
    try {
      const data = await runGapDetect(selectedNoteIds, selectedDocId)
      setResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed")
    } finally {
      setIsLoading(false)
    }
  }

  function handleClose() {
    setSelectedDocId("")
    setSelectedNoteIds([])
    setResult(null)
    setError(null)
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose() }}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Compare Notes with Book</DialogTitle>
          <DialogDescription>
            Select a book and notes to find concepts you may have missed.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          {isFetching ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading documents and notes...
            </div>
          ) : (
            <>
              {/* Document selector */}
              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-medium">Book to compare against</label>
                <select
                  value={selectedDocId}
                  onChange={(e) => setSelectedDocId(e.target.value)}
                  className="rounded border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="">-- Select a book --</option>
                  {documents.map((d) => (
                    <option key={d.id} value={d.id}>{d.title}</option>
                  ))}
                </select>
              </div>

              {/* Note multi-select */}
              {notes.length > 0 ? (
                <div className="flex flex-col gap-1.5">
                  <label className="text-sm font-medium">
                    Your notes to analyse
                    {selectedNoteIds.length > 0 && (
                      <span className="ml-2 text-xs text-muted-foreground">
                        ({selectedNoteIds.length} selected)
                      </span>
                    )}
                  </label>
                  <div className="max-h-40 overflow-y-auto rounded border border-border bg-background">
                    {notes.map((note) => (
                      <label
                        key={note.id}
                        className="flex cursor-pointer items-start gap-2 px-3 py-2 text-sm hover:bg-accent/50"
                      >
                        <input
                          type="checkbox"
                          checked={selectedNoteIds.includes(note.id)}
                          onChange={() => toggleNoteId(note.id)}
                          className="mt-0.5 shrink-0"
                        />
                        <span className="line-clamp-2 text-foreground">{note.content}</span>
                      </label>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No notes yet. Create some notes first to compare with a book.
                </p>
              )}

              {/* Analyze button */}
              <button
                onClick={() => { void handleAnalyze() }}
                disabled={!canAnalyze || isLoading}
                className="flex items-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50 disabled:cursor-not-allowed hover:bg-primary/90 transition-colors w-fit"
              >
                {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
                {isLoading ? "Analysing..." : "Analyse"}
              </button>
            </>
          )}

          {/* Error */}
          {error && (
            <p className="text-sm text-red-600 bg-red-50 rounded px-3 py-2 border border-red-200">
              {error}
            </p>
          )}

          {/* Results */}
          {result && (
            <div className="flex flex-col gap-3">
              {result.gaps.length > 0 ? (
                <div className="flex flex-col gap-1.5">
                  <p className="text-sm font-medium text-foreground">Gaps (concepts you may have missed)</p>
                  <ul className="flex flex-col gap-1 rounded border border-amber-200 bg-amber-50 p-3">
                    {result.gaps.map((g, i) => (
                      <li key={i} className="text-sm text-amber-900">
                        {g}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 border border-green-200">
                  Great coverage -- no significant gaps detected.
                </p>
              )}

              {result.covered.length > 0 && (
                <div className="flex flex-col gap-1.5">
                  <p className="text-sm font-medium text-foreground">Well covered</p>
                  <ul className="flex flex-col gap-1 rounded border border-green-200 bg-green-50 p-3">
                    {result.covered.map((c, i) => (
                      <li key={i} className="text-sm text-green-900">
                        {c}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {result.gaps.length === 0 && result.covered.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No analysis available. Try selecting different notes or a different book.
                </p>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <button
            onClick={handleClose}
            className="rounded border border-border px-4 py-2 text-sm hover:bg-muted transition-colors"
          >
            {result ? "Done" : "Cancel"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
