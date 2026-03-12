/**
 * Study tab — Flashcard section (S20b) and Progress section placeholder (S23b).
 *
 * Flashcard section:
 *  - Generate panel: count selector, scope (full/section), Generate button
 *  - Flashcard list: show/hide answer, inline edit, delete with confirmation
 *  - Bottom bar: card count, Start Studying (S21b), CSV export
 * Study session (S21b):
 *  - Full-screen StudySession replaces tab content when studying
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import {
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Download,
  Loader2,
  Pencil,
  PlayCircle,
  Trash2,
  X,
} from "lucide-react"
import { toast } from "sonner"
import { Card } from "@/components/ui/card"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { logger } from "@/lib/logger"
import { useAppStore } from "@/store"
import { StudySession } from "@/components/StudySession"
import { ProgressDashboard } from "@/components/ProgressDashboard"

// ---------------------------------------------------------------------------
// Document list for the in-tab picker
// ---------------------------------------------------------------------------

interface DocListItem {
  id: string
  title: string
}

async function fetchDocList(): Promise<DocListItem[]> {
  const res = await fetch(`${API_BASE}/documents?sort=newest&page=1&page_size=100`)
  if (!res.ok) return []
  const data = (await res.json()) as { items: DocListItem[] }
  return data.items ?? []
}

const API_BASE = "http://localhost:8000"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Flashcard {
  id: string
  document_id: string
  chunk_id: string
  question: string
  answer: string
  source_excerpt: string
  is_user_edited: boolean
  fsrs_state: string
  reps: number
  lapses: number
  due_date: string | null
  created_at: string
}

interface SectionItem {
  id: string
  heading: string
  level: number
  section_order: number
}

interface DocumentSections {
  sections: SectionItem[]
}

interface GapResult {
  section_heading: string | null
  weak_card_count: number
  avg_stability: number
  sample_questions: string[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function fetchFlashcards(documentId: string): Promise<Flashcard[]> {
  const res = await fetch(`${API_BASE}/flashcards/${documentId}`)
  if (!res.ok) return []
  return res.json() as Promise<Flashcard[]>
}

async function fetchDocumentSections(documentId: string): Promise<DocumentSections> {
  const res = await fetch(`${API_BASE}/documents/${documentId}`)
  if (!res.ok) return { sections: [] }
  return res.json() as Promise<DocumentSections>
}

async function fetchGaps(documentId: string): Promise<GapResult[]> {
  const res = await fetch(`${API_BASE}/study/gaps/${documentId}`)
  if (!res.ok) return []
  return res.json() as Promise<GapResult[]>
}

class GenerateError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function generateFlashcards(req: {
  document_id: string
  scope: "full" | "section"
  section_heading: string | null
  count: number
  difficulty: "easy" | "medium" | "hard"
}): Promise<Flashcard[]> {
  const res = await fetch(`${API_BASE}/flashcards/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new GenerateError(res.status, "Failed to generate flashcards")
  return res.json() as Promise<Flashcard[]>
}

async function updateFlashcard(
  id: string,
  data: { question?: string; answer?: string },
): Promise<Flashcard> {
  const res = await fetch(`${API_BASE}/flashcards/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error("Failed to update flashcard")
  return res.json() as Promise<Flashcard>
}

async function deleteFlashcard(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/flashcards/${id}`, { method: "DELETE" })
  if (!res.ok) throw new Error("Failed to delete flashcard")
}

async function deleteAllFlashcards(documentId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/flashcards/document/${documentId}`, {
    method: "DELETE",
  })
  if (!res.ok) throw new Error("Failed to delete all flashcards")
}

// ---------------------------------------------------------------------------
// FlashcardCard
// ---------------------------------------------------------------------------

interface FlashcardCardProps {
  card: Flashcard
  onUpdate: (id: string, data: { question?: string; answer?: string }) => void
  onDelete: (id: string) => void
  isUpdating: boolean
  isDeleting: boolean
}

function FlashcardCard({
  card,
  onUpdate,
  onDelete,
  isUpdating,
  isDeleting,
}: FlashcardCardProps) {
  const [showAnswer, setShowAnswer] = useState(false)
  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [editQuestion, setEditQuestion] = useState(card.question)
  const [editAnswer, setEditAnswer] = useState(card.answer)

  function handleEditSave() {
    onUpdate(card.id, { question: editQuestion, answer: editAnswer })
    setEditing(false)
  }

  function handleEditCancel() {
    setEditQuestion(card.question)
    setEditAnswer(card.answer)
    setEditing(false)
  }

  return (
    <Card className="flex flex-col gap-3">
      {/* Question */}
      <div className="flex items-start justify-between gap-2">
        {editing ? (
          <textarea
            value={editQuestion}
            onChange={(e) => setEditQuestion(e.target.value)}
            className="flex-1 resize-none rounded border border-border bg-background p-1 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            rows={2}
          />
        ) : (
          <p className="flex-1 text-sm font-medium text-foreground">{card.question}</p>
        )}

        {!editing && !confirmDelete && (
          <div className="flex shrink-0 gap-1">
            <button
              onClick={() => setEditing(true)}
              className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
              title="Edit"
            >
              <Pencil size={14} />
            </button>
            <button
              onClick={() => setConfirmDelete(true)}
              className="rounded p-1 text-muted-foreground hover:bg-red-50 hover:text-red-600"
              title="Delete"
            >
              <Trash2 size={14} />
            </button>
          </div>
        )}
      </div>

      {/* Answer */}
      {editing ? (
        <textarea
          value={editAnswer}
          onChange={(e) => setEditAnswer(e.target.value)}
          className="resize-none rounded border border-border bg-background p-1 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          rows={3}
          placeholder="Answer..."
        />
      ) : (
        <div>
          <button
            onClick={() => setShowAnswer((prev) => !prev)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            {showAnswer ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {showAnswer ? "Hide answer" : "Show answer"}
          </button>
          {showAnswer && (
            <MarkdownRenderer className="mt-1 text-sm">{card.answer}</MarkdownRenderer>
          )}
        </div>
      )}

      {/* Edit actions */}
      {editing && (
        <div className="flex gap-2">
          <button
            onClick={handleEditSave}
            disabled={isUpdating}
            className="flex items-center gap-1 rounded bg-primary px-3 py-1 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {isUpdating ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
            Save
          </button>
          <button
            onClick={handleEditCancel}
            className="flex items-center gap-1 rounded border border-border px-3 py-1 text-xs text-muted-foreground hover:bg-accent"
          >
            <X size={12} />
            Cancel
          </button>
        </div>
      )}

      {/* Delete confirmation */}
      {confirmDelete && (
        <div className="flex items-center gap-2 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-700">
          <span className="flex-1">Delete this flashcard?</span>
          <button
            onClick={() => {
              onDelete(card.id)
              setConfirmDelete(false)
            }}
            disabled={isDeleting}
            className="flex items-center gap-1 rounded bg-red-600 px-2 py-1 text-white hover:bg-red-700 disabled:opacity-50"
          >
            {isDeleting ? <Loader2 size={10} className="animate-spin" /> : null}
            Delete
          </button>
          <button
            onClick={() => setConfirmDelete(false)}
            className="rounded border border-red-300 px-2 py-1 hover:bg-red-100"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Footer: FSRS state badge */}
      <div className="flex items-center gap-2 border-t border-border pt-2">
        <span className="rounded-full bg-secondary px-2 py-0.5 text-xs text-secondary-foreground capitalize">
          {card.fsrs_state}
        </span>
        {card.is_user_edited && (
          <span className="text-xs text-muted-foreground italic">edited</span>
        )}
        <span className="ml-auto text-xs text-muted-foreground">
          {card.reps} rep{card.reps !== 1 ? "s" : ""}
        </span>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// WeakAreasPanel
// ---------------------------------------------------------------------------

function fragileBarColor(avgStability: number): string {
  if (avgStability < 2) return "bg-red-500"
  if (avgStability <= 5) return "bg-amber-400"
  return "bg-green-500"
}

interface WeakAreasPanelProps {
  documentId: string
  onSelectSection: (heading: string) => void
}

function WeakAreasPanel({ documentId, onSelectSection }: WeakAreasPanelProps) {
  const { data: gaps = [], isLoading } = useQuery<GapResult[]>({
    queryKey: ["gaps", documentId],
    queryFn: () => fetchGaps(documentId),
    staleTime: 30_000,
  })

  if (isLoading) return null
  if (gaps.length === 0) return null

  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-base font-semibold text-foreground">Weak Areas</h3>
      <div className="flex flex-col gap-2">
        {gaps.map((gap, i) => {
          const pct = Math.min(100, Math.round((gap.avg_stability / 10) * 100))
          const heading = gap.section_heading ?? "Unsectioned"
          return (
            <button
              key={i}
              onClick={() => {
                if (gap.section_heading) onSelectSection(gap.section_heading)
              }}
              className="flex flex-col gap-1.5 rounded-lg border border-border bg-muted/20 p-3 text-left hover:bg-muted/40 transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="flex-1 text-sm font-medium text-foreground">{heading}</span>
                <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                  {gap.weak_card_count} weak
                </span>
              </div>
              {/* Fragility bar */}
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
                <div
                  className={`h-full rounded-full transition-all ${fragileBarColor(gap.avg_stability)}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-xs text-muted-foreground">
                avg stability: {gap.avg_stability.toFixed(2)}
              </span>
            </button>
          )
        })}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// GeneratePanel
// ---------------------------------------------------------------------------

interface GeneratePanelProps {
  documentId: string
  sections: SectionItem[]
  onGenerate: (req: {
    scope: "full" | "section"
    section_heading: string | null
    count: number
    difficulty: "easy" | "medium" | "hard"
  }) => void
  onRegenerate: (req: {
    scope: "full" | "section"
    section_heading: string | null
    count: number
    difficulty: "easy" | "medium" | "hard"
  }) => void
  isGenerating: boolean
  preselectedSection?: string | null
}

const COUNT_OPTIONS = [5, 10, 20, 50]
const DIFFICULTY_OPTIONS = [
  { value: "easy", label: "Easy" },
  { value: "medium", label: "Medium" },
  { value: "hard", label: "Hard" },
]

function GeneratePanel({
  documentId: _documentId,
  sections,
  onGenerate,
  onRegenerate,
  isGenerating,
  preselectedSection,
}: GeneratePanelProps) {
  const [count, setCount] = useState(10)
  const [scope, setScope] = useState<"full" | "section">("full")
  const [sectionHeading, setSectionHeading] = useState<string | null>(null)
  const [difficulty, setDifficulty] = useState<"easy" | "medium" | "hard">("medium")

  // Sync scope/heading when a gap section is clicked from outside
  useEffect(() => {
    if (preselectedSection != null) {
      setScope("section")
      setSectionHeading(preselectedSection)
    }
  }, [preselectedSection])

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-muted/30 p-4">
      {/* Count */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">Count</label>
        <select
          value={count}
          onChange={(e) => setCount(Number(e.target.value))}
          className="rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        >
          {COUNT_OPTIONS.map((n) => (
            <option key={n} value={n}>
              {n} cards
            </option>
          ))}
        </select>
      </div>

      {/* Difficulty */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">Difficulty</label>
        <select
          value={difficulty}
          onChange={(e) => setDifficulty(e.target.value as "easy" | "medium" | "hard")}
          className="rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        >
          {DIFFICULTY_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* Scope */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">Scope</label>
        <select
          value={scope}
          onChange={(e) => {
            const v = e.target.value as "full" | "section"
            setScope(v)
            if (v === "full") setSectionHeading(null)
          }}
          className="rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        >
          <option value="full">Full document</option>
          <option value="section">By section</option>
        </select>
      </div>

      {/* Section picker */}
      {scope === "section" && sections.length > 0 && (
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-muted-foreground">Section</label>
          <select
            value={sectionHeading ?? ""}
            onChange={(e) => setSectionHeading(e.target.value || null)}
            className="max-w-[240px] rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="">Select section...</option>
            {sections.map((s) => (
              <option key={s.id} value={s.heading}>
                {s.heading}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={() => onGenerate({ scope, section_heading: sectionHeading, count, difficulty })}
          disabled={isGenerating || (scope === "section" && !sectionHeading)}
          className="flex items-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {isGenerating && <Loader2 size={14} className="animate-spin" />}
          Generate
        </button>
        <button
          onClick={() => onRegenerate({ scope, section_heading: sectionHeading, count, difficulty })}
          disabled={isGenerating || (scope === "section" && !sectionHeading)}
          className="flex items-center gap-2 rounded border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
          title="Delete all current cards and generate new ones"
        >
          Regenerate
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Study page
// ---------------------------------------------------------------------------

type GenerateErrorKind = "ollama_offline" | "server_error" | null

export default function Study() {
  const activeDocumentId = useAppStore((s) => s.activeDocumentId)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const queryClient = useQueryClient()
  const [studying, setStudying] = useState(false)
  // Track section pre-selected by clicking a gap item
  const [selectedGapSection, setSelectedGapSection] = useState<string | null>(null)
  const [generateErrorKind, setGenerateErrorKind] = useState<GenerateErrorKind>(null)
  const mountTime = useRef(Date.now())

  // Document list for the in-tab picker
  const { data: docList = [] } = useQuery<DocListItem[]>({
    queryKey: ["study-doc-list"],
    queryFn: fetchDocList,
    staleTime: 30_000,
  })

  useEffect(() => {
    logger.info("[Study] mounted")
  }, [])

  // Flashcard list
  const { data: cards = [], isLoading: cardsLoading, isError: cardsError } = useQuery<Flashcard[]>({
    queryKey: ["flashcards", activeDocumentId],
    queryFn: () => fetchFlashcards(activeDocumentId!),
    enabled: !!activeDocumentId,
  })

  useEffect(() => {
    if (!cardsLoading && activeDocumentId) {
      const elapsed = Date.now() - mountTime.current
      logger.info("[Study] loaded", { duration_ms: elapsed, itemCount: cards.length })
    }
  }, [cardsLoading, activeDocumentId, cards.length])

  // Document sections (for section scope dropdown)
  const { data: docData } = useQuery<DocumentSections>({
    queryKey: ["document-sections", activeDocumentId],
    queryFn: () => fetchDocumentSections(activeDocumentId!),
    enabled: !!activeDocumentId,
  })

  const sections = docData?.sections ?? []

  // Generate mutation
  const generateMutation = useMutation({
    mutationFn: (req: {
      scope: "full" | "section"
      section_heading: string | null
      count: number
      difficulty: "easy" | "medium" | "hard"
    }) =>
      generateFlashcards({
        document_id: activeDocumentId!,
        ...req,
      }),
    onSuccess: (newCards) => {
      setGenerateErrorKind(null)
      void queryClient.invalidateQueries({ queryKey: ["flashcards", activeDocumentId] })
      toast.success(`Generated ${newCards.length} flashcard${newCards.length !== 1 ? "s" : ""}`)
    },
    onError: (err: unknown) => {
      const status = err instanceof GenerateError ? err.status : 0
      if (status === 503) {
        setGenerateErrorKind("ollama_offline")
      } else {
        setGenerateErrorKind("server_error")
      }
    },
  })

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { question?: string; answer?: string } }) =>
      updateFlashcard(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["flashcards", activeDocumentId] })
      toast.success("Flashcard updated")
    },
    onError: () => toast.error("Failed to update flashcard"),
  })

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteFlashcard(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["flashcards", activeDocumentId] })
      toast.success("Flashcard deleted")
    },
    onError: () => toast.error("Failed to delete flashcard"),
  })

  // Delete all mutation
  const deleteAllMutation = useMutation({
    mutationFn: () => deleteAllFlashcards(activeDocumentId!),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["flashcards", activeDocumentId] })
    },
    onError: () => toast.error("Failed to clear flashcards"),
  })

  async function handleRegenerate(req: {
    scope: "full" | "section"
    section_heading: string | null
    count: number
    difficulty: "easy" | "medium" | "hard"
  }) {
    if (!activeDocumentId) return
    const confirmed = window.confirm(
      "This will delete all current flashcards for this document and generate new ones. Continue?"
    )
    if (!confirmed) return

    setGenerateErrorKind(null)
    try {
      await deleteAllMutation.mutateAsync()
      await generateMutation.mutateAsync(req)
    } catch (err) {
      logger.error("Regenerate failed", { err })
    }
  }

  function handleExportCsv() {
    if (!activeDocumentId) return
    window.open(`${API_BASE}/flashcards/${activeDocumentId}/export/csv`, "_blank")
  }

  // Show StudySession when user clicks Start Studying
  if (studying) {
    return (
      <StudySession
        documentId={activeDocumentId}
        onExit={() => {
          setStudying(false)
          void queryClient.invalidateQueries({ queryKey: ["flashcards", activeDocumentId] })
        }}
      />
    )
  }

  return (
    <div className="flex h-full flex-col gap-6 overflow-auto p-6">
      {/* Document selector */}
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-muted-foreground shrink-0">Document</label>
        <select
          value={activeDocumentId ?? ""}
          onChange={(e) => setActiveDocument(e.target.value || null)}
          className="rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring max-w-xs"
        >
          <option value="">Select a document…</option>
          {docList.map((doc) => (
            <option key={doc.id} value={doc.id}>{doc.title}</option>
          ))}
        </select>
      </div>

      {!activeDocumentId ? (
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-muted-foreground">Select a document above to get started.</p>
        </div>
      ) : (
      <>
      {/* Flashcards section */}
      <section className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold text-foreground">Flashcards</h2>

        <GeneratePanel
          documentId={activeDocumentId}
          sections={sections}
          onGenerate={(req) => { setGenerateErrorKind(null); generateMutation.mutate(req) }}
          onRegenerate={handleRegenerate}
          isGenerating={generateMutation.isPending || deleteAllMutation.isPending}
          preselectedSection={selectedGapSection}
        />

        {/* Inline generate error banners */}
        {generateErrorKind === "ollama_offline" && (
          <div className="flex items-center gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            <span className="flex-1">
              Ollama is not running. To generate flashcards, run:{" "}
              <code className="rounded bg-amber-100 px-1 py-0.5 font-mono text-xs">ollama serve</code>
            </span>
            <button
              onClick={() => void navigator.clipboard.writeText("ollama serve")}
              className="flex items-center gap-1 rounded border border-amber-300 bg-white px-2 py-1 text-xs text-amber-700 hover:bg-amber-50"
              title="Copy command"
            >
              <Copy size={11} />
              Copy
            </button>
          </div>
        )}
        {generateErrorKind === "server_error" && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            Flashcard generation failed. Please try again.
          </div>
        )}

        {cardsLoading ? (
          <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
            <Loader2 size={24} className="animate-spin" />
            <span className="text-sm">Loading your cards...</span>
          </div>
        ) : cardsError ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            Failed to load flashcards. Please try refreshing.
          </div>
        ) : cards.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <p className="text-sm text-muted-foreground">
              No flashcards yet. Generate some above.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {cards.map((card) => (
              <FlashcardCard
                key={card.id}
                card={card}
                onUpdate={(id, data) => updateMutation.mutate({ id, data })}
                onDelete={(id) => deleteMutation.mutate(id)}
                isUpdating={updateMutation.isPending}
                isDeleting={deleteMutation.isPending}
              />
            ))}
          </div>
        )}

        {/* Bottom bar */}
        {cards.length > 0 && (
          <div className="flex items-center gap-3 border-t border-border pt-4">
            <span className="text-sm text-muted-foreground">
              {cards.length} card{cards.length !== 1 ? "s" : ""}
            </span>
            <div className="ml-auto flex gap-2">
              <button
                onClick={handleExportCsv}
                className="flex items-center gap-2 rounded border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <Download size={14} />
                Export CSV
              </button>
              <button
                onClick={() => setStudying(true)}
                className="flex items-center gap-2 rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                <PlayCircle size={14} />
                Start Studying
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Weak Areas panel */}
      <WeakAreasPanel
        documentId={activeDocumentId}
        onSelectSection={(heading) => {
          setSelectedGapSection(heading)
          // Scroll to top to reveal pre-scoped GeneratePanel
          window.scrollTo({ top: 0, behavior: "smooth" })
        }}
      />

      {/* Progress dashboard (S23b) */}
      <section className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold text-foreground">Progress</h2>
        <ProgressDashboard documentId={activeDocumentId} />
      </section>
      </>
      )}
    </div>
  )
}
