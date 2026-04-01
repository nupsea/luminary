/**
 * GapDetectDialog -- compare user notes with a book and surface gaps.
 *
 * Props:
 *   open     — controls visibility
 *   onClose  — called to close
 *
 * Flow:
 *   Quick mode (default, S197): auto-populates notes from document's auto-collection.
 *   Advanced mode: user manually searches and selects notes.
 *
 * States: loading (skeleton), error (amber), empty (placeholder).
 * 503 shown as 'Ollama is unavailable. Start it with: ollama serve'.
 */

import { Search, X, Loader2, CheckSquare, Square, ChevronDown, ChevronUp } from "lucide-react"
import { useMemo, useState, useEffect } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

import { API_BASE } from "@/lib/config"

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

interface AutoCollection {
  id: string
  name: string
  note_count: number
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
    return notes.map((n) => ({ id: n.id, content: n.content.slice(0, 150) }))
  } catch {
    return []
  }
}

async function fetchAutoCollection(docId: string): Promise<AutoCollection | null> {
  try {
    const res = await fetch(`${API_BASE}/collections/by-document/${docId}`)
    if (!res.ok) return null
    return (await res.json()) as AutoCollection
  } catch {
    return null
  }
}

async function fetchCollectionNotes(collectionId: string): Promise<NoteStub[]> {
  try {
    const res = await fetch(`${API_BASE}/notes?collection_id=${collectionId}`)
    if (!res.ok) return []
    const notes = (await res.json()) as { id: string; content: string }[]
    return notes.map((n) => ({ id: n.id, content: n.content.slice(0, 150) }))
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
  const [noteSearch, setNoteSearch] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [isFetching, setIsFetching] = useState(false)
  const [result, setResult] = useState<GapDetectResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  // S197: quick/advanced mode
  const [mode, setMode] = useState<"quick" | "advanced">("quick")
  const [quickNoteCount, setQuickNoteCount] = useState<number | null>(null)
  const [quickFetching, setQuickFetching] = useState(false)
  const [quickError, setQuickError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setIsFetching(true)
      void fetchDocuments().then((docs) => {
        setDocuments(docs)
        setIsFetching(false)
      })
    }
  }, [open])

  // S197: auto-fetch notes from auto-collection when quick mode + doc selected
  useEffect(() => {
    if (mode !== "quick" || !selectedDocId) {
      setQuickNoteCount(null)
      setQuickError(null)
      return
    }
    let cancelled = false
    setQuickFetching(true)
    setQuickError(null)
    setQuickNoteCount(null)

    void (async () => {
      const coll = await fetchAutoCollection(selectedDocId)
      if (cancelled) return
      if (!coll) {
        setQuickNoteCount(0)
        setQuickFetching(false)
        return
      }
      const collNotes = await fetchCollectionNotes(coll.id)
      if (cancelled) return
      setSelectedNoteIds(collNotes.map((n) => n.id))
      setQuickNoteCount(collNotes.length)
      setQuickFetching(false)
    })()

    return () => { cancelled = true }
  }, [mode, selectedDocId])

  // Fetch all notes only when switching to advanced mode
  useEffect(() => {
    if (mode === "advanced" && notes.length === 0) {
      void fetchNoteStubs().then(setNotes)
    }
  }, [mode, notes.length])

  const filteredNotes = useMemo(() => {
    if (!noteSearch.trim()) return notes
    const q = noteSearch.toLowerCase()
    return notes.filter((n) => n.content.toLowerCase().includes(q))
  }, [notes, noteSearch])

  const canAnalyze = !!selectedDocId && selectedNoteIds.length > 0

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
    setNoteSearch("")
    setResult(null)
    setError(null)
    setMode("quick")
    setQuickNoteCount(null)
    setQuickError(null)
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose() }}>
      <DialogContent className="max-w-2xl max-h-[90vh] flex flex-col p-0 overflow-hidden">
        <DialogHeader className="p-6 pb-2">
          <DialogTitle className="text-xl">Compare Notes with Book</DialogTitle>
          <DialogDescription>
            Select a book and notes to find concepts you may have missed.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          <div className="flex flex-col gap-6">
            {isFetching ? (
              <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                Loading documents...
              </div>
            ) : (
              <>
                {/* Document selector */}
                <div className="flex flex-col gap-2">
                  <label className="text-sm font-semibold text-foreground">1. Book to compare against</label>
                  <select
                    value={selectedDocId}
                    onChange={(e) => { setSelectedDocId(e.target.value); setSelectedNoteIds([]); setResult(null); setError(null) }}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                  >
                    <option value="">-- Select a book --</option>
                    {documents.map((d) => (
                      <option key={d.id} value={d.id}>{d.title}</option>
                    ))}
                  </select>
                </div>

                {/* Note selection section */}
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-semibold text-foreground">2. Notes to compare</label>
                    <button
                      onClick={() => { setMode(mode === "quick" ? "advanced" : "quick"); setSelectedNoteIds([]) }}
                      className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                    >
                      {mode === "quick" ? (
                        <>Advanced <ChevronDown size={12} /></>
                      ) : (
                        <>Quick compare <ChevronUp size={12} /></>
                      )}
                    </button>
                  </div>

                  {/* Quick mode: auto-collection summary */}
                  {mode === "quick" && (
                    <div className="rounded-lg border border-border bg-muted/30 p-4">
                      {!selectedDocId ? (
                        <p className="text-sm text-muted-foreground">Select a book above to auto-load your reading notes.</p>
                      ) : quickFetching ? (
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                          <Loader2 size={14} className="animate-spin" />
                          Loading notes from reading collection...
                        </div>
                      ) : quickError ? (
                        <p className="text-sm text-red-600">{quickError}</p>
                      ) : quickNoteCount === 0 ? (
                        <p className="text-sm text-muted-foreground">No reading notes found for this document. Take some notes in the reader first, or switch to Advanced mode to select notes manually.</p>
                      ) : quickNoteCount !== null && quickNoteCount < 3 ? (
                        <p className="text-sm text-amber-700">Only {quickNoteCount} note(s) found. Take a few more notes while reading for better gap analysis, or switch to Advanced mode.</p>
                      ) : quickNoteCount !== null ? (
                        <p className="text-sm text-foreground">Will use <span className="font-semibold">{quickNoteCount}</span> notes from this document's reading collection.</p>
                      ) : null}
                    </div>
                  )}

                  {/* Advanced mode: manual note search and selection */}
                  {mode === "advanced" && (
                    <div className="flex flex-col gap-2 rounded-lg border border-border bg-muted/30 p-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-muted-foreground font-medium">
                          {selectedNoteIds.length} selected
                        </span>
                      </div>

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
                            {notes.length === 0 ? "No notes found." : "No matching notes."}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* Action button */}
                <div className="flex justify-center pt-2">
                  <button
                    onClick={() => { void handleAnalyze() }}
                    disabled={!canAnalyze || isLoading}
                    className="flex h-10 items-center gap-2 rounded-md bg-primary px-8 py-2 text-sm font-semibold text-primary-foreground shadow transition-colors hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isLoading ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Analysing...
                      </>
                    ) : (
                      "Run Analysis"
                    )}
                  </button>
                </div>
              </>
            )}

            {/* Error */}
            {error && (
              <div className="rounded-md border border-red-200 bg-red-50 p-4">
                <p className="text-sm font-medium text-red-800">{error}</p>
              </div>
            )}

            {/* Results */}
            {result && (
              <div className="flex flex-col gap-5 border-t border-border pt-6 animate-in fade-in slide-in-from-top-2">
                <h3 className="text-lg font-bold text-foreground">Analysis Results</h3>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-bold text-amber-700 uppercase tracking-tight">Knowledge Gaps</p>
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-bold text-amber-700">
                        {result.gaps.length}
                      </span>
                    </div>
                    <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-4">
                      {result.gaps.length > 0 ? (
                        <ul className="list-disc pl-4 flex flex-col gap-2">
                          {result.gaps.map((g, i) => (
                            <li key={i} className="text-sm text-amber-900 leading-snug">
                              {g}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-sm text-green-700 italic">No significant gaps detected!</p>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-bold text-green-700 uppercase tracking-tight">Well Covered</p>
                      <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-bold text-green-700">
                        {result.covered.length}
                      </span>
                    </div>
                    <div className="rounded-lg border border-green-200 bg-green-50/50 p-4">
                      {result.covered.length > 0 ? (
                        <ul className="list-disc pl-4 flex flex-col gap-2">
                          {result.covered.map((c, i) => (
                            <li key={i} className="text-sm text-green-900 leading-snug">
                              {c}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-sm text-muted-foreground italic">No covered concepts identified.</p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="border-t border-border p-4 bg-muted/10">
          <button
            onClick={handleClose}
            className="rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent transition-colors"
          >
            {result ? "Close" : "Cancel"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
