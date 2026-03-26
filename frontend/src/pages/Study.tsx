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
import { Fragment, lazy, Suspense, useEffect, useRef, useState } from "react"
import {
  AlertCircle,
  BookOpen,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Download,
  Folder,
  Loader2,
  Pencil,
  PlayCircle,
  Plus,
  Trash2,
  X,
  Zap,
} from "lucide-react"
import { useNavigate } from "react-router-dom"
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { toast } from "sonner"
import { Card } from "@/components/ui/card"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { logger } from "@/lib/logger"
import { useAppStore } from "@/store"
import { StudySession } from "@/components/StudySession"
// ProgressDashboard is Recharts-heavy — lazy-load so Recharts stays out of the initial Study chunk
const ProgressDashboard = lazy(() =>
  import("@/components/ProgressDashboard").then((m) => ({ default: m.ProgressDashboard }))
)

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

import { API_BASE } from "@/lib/config"
import {
  computeMasteryPct,
  getDeckDisplayName,
  selectSmartMode,
} from "@/lib/studyUtils"

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
  // S137: Bloom's Taxonomy fields
  flashcard_type: string | null
  bloom_level: number | null
  // S154: cloze deletion text with {{term}} markers; null for non-cloze cards
  cloze_text: string | null
}

interface SectionItem {
  id: string
  heading: string
  level: number
  section_order: number
}

interface EntityPair {
  name_a: string
  name_b: string
  relation_label: string
  confidence: number
}

interface EntityPairsResponse {
  pairs: EntityPair[]
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

interface LearningGoal {
  id: string
  document_id: string
  title: string
  target_date: string
  created_at: string
}

interface AtRiskCard {
  id: string
  question: string
  projected_retention_pct: number
}

interface ReadinessResult {
  on_track: boolean
  projected_retention_pct: number
  at_risk_card_count: number
  at_risk_cards: AtRiskCard[]
}

interface StrugglingCard {
  flashcard_id: string
  document_id: string | null
  question: string
  again_count: number
  source_section_id: string | null
}

// S160: Deck health report types
interface HealthSection {
  section_id: string
  section_heading: string
  card_count: number
}

interface DeckHealthReport {
  orphaned: number
  orphaned_ids: string[]
  mastered: number
  mastered_ids: string[]
  stale: number
  stale_ids: string[]
  uncovered_sections: number
  uncovered_section_ids: string[]
  hotspot_sections: HealthSection[]
}

// S169: Deck list type
interface DeckItem {
  deck: string
  source_type: "document" | "collection" | "note"
  card_count: number
  document_id: string | null
  collection_id: string | null
}

// S153: Bloom's taxonomy coverage audit types
interface BloomGap {
  section_id: string
  section_heading: string
  missing_bloom_levels: number[]
}

interface BloomSectionStat {
  section_heading: string
  by_bloom_level: Record<string, number>
  has_level_3_plus: boolean
}

interface CoverageReport {
  total_cards: number
  by_bloom_level: Record<string, number>
  by_section: Record<string, BloomSectionStat>
  coverage_score: number
  gaps: BloomGap[]
}

interface StudySessionItem {
  id: string
  started_at: string
  ended_at: string | null
  duration_minutes: number | null
  cards_reviewed: number
  cards_correct: number
  accuracy_pct: number | null
  document_id: string | null
  document_title: string | null
  mode: string
}

interface SessionListResponse {
  items: StudySessionItem[]
  total: number
  page: number
  page_size: number
}

interface SessionCardDetail {
  flashcard_id: string
  question: string
  rating: string
  is_correct: boolean
  reviewed_at: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function fetchFlashcards(
  documentId: string,
  sectionId?: string | null,
  bloomLevelMin?: number | null,
): Promise<Flashcard[]> {
  const params = new URLSearchParams()
  if (sectionId) params.set("section_id", sectionId)
  if (bloomLevelMin != null) params.set("bloom_level_min", String(bloomLevelMin))
  const query = params.toString()
  const res = await fetch(`${API_BASE}/flashcards/${documentId}${query ? `?${query}` : ""}`)
  if (!res.ok) return []
  return res.json() as Promise<Flashcard[]>
}

async function fetchDecks(): Promise<DeckItem[]> {
  const res = await fetch(`${API_BASE}/flashcards/decks`)
  if (!res.ok) return []
  return res.json() as Promise<DeckItem[]>
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

async function fetchGoals(): Promise<LearningGoal[]> {
  const res = await fetch(`${API_BASE}/goals`)
  if (!res.ok) throw new Error("Failed to load goals")
  return res.json() as Promise<LearningGoal[]>
}

async function createGoal(body: {
  document_id: string
  title: string
  target_date: string
}): Promise<LearningGoal> {
  const res = await fetch(`${API_BASE}/goals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error("Failed to create goal")
  return res.json() as Promise<LearningGoal>
}

async function deleteGoalApi(goalId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/goals/${encodeURIComponent(goalId)}`, {
    method: "DELETE",
  })
  if (!res.ok) throw new Error("Failed to delete goal")
}

async function fetchReadiness(goalId: string): Promise<ReadinessResult> {
  const res = await fetch(`${API_BASE}/goals/${encodeURIComponent(goalId)}/readiness`)
  if (!res.ok) throw new Error("Failed to compute readiness")
  return res.json() as Promise<ReadinessResult>
}

async function fetchStrugglingCards(documentId: string): Promise<StrugglingCard[]> {
  const res = await fetch(
    `${API_BASE}/study/struggling?document_id=${encodeURIComponent(documentId)}`
  )
  if (!res.ok) throw new Error("Failed to load struggling cards")
  return res.json() as Promise<StrugglingCard[]>
}

async function fetchSessions(page: number, pageSize: number): Promise<SessionListResponse> {
  const res = await fetch(`${API_BASE}/study/sessions?page=${page}&page_size=${pageSize}`)
  if (!res.ok) throw new Error("Failed to load session history")
  return res.json() as Promise<SessionListResponse>
}

async function fetchSessionCards(sessionId: string): Promise<SessionCardDetail[]> {
  const res = await fetch(`${API_BASE}/study/sessions/${encodeURIComponent(sessionId)}/cards`)
  if (!res.ok) throw new Error("Failed to load session cards")
  return res.json() as Promise<SessionCardDetail[]>
}

class GenerateError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function fetchEntityPairs(documentId: string): Promise<EntityPairsResponse> {
  const res = await fetch(
    `${API_BASE}/flashcards/entity-pairs?document_id=${encodeURIComponent(documentId)}`
  )
  if (!res.ok) return { pairs: [] }
  return res.json() as Promise<EntityPairsResponse>
}

async function generateFromGraph(req: {
  document_id: string
  k: number
}): Promise<Flashcard[]> {
  const res = await fetch(`${API_BASE}/flashcards/generate-from-graph`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new GenerateError(res.status, "Failed to generate entity flashcards")
  return res.json() as Promise<Flashcard[]>
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

// S154: Cloze generation API helper
async function generateClozeFlashcards(
  sectionId: string,
  count: number,
): Promise<Flashcard[]> {
  const res = await fetch(
    `${API_BASE}/flashcards/cloze/${encodeURIComponent(sectionId)}?count=${count}`,
    { method: "POST" },
  )
  if (!res.ok) throw new GenerateError(res.status, "Failed to generate cloze flashcards")
  return res.json() as Promise<Flashcard[]>
}

// S153: Bloom's coverage audit API helpers
async function fetchAudit(documentId: string): Promise<CoverageReport> {
  const res = await fetch(`${API_BASE}/flashcards/audit/${documentId}`)
  if (!res.ok) throw new Error("Failed to load deck health")
  return res.json() as Promise<CoverageReport>
}

async function fillAuditGaps(documentId: string): Promise<{ created: number }> {
  const res = await fetch(`${API_BASE}/flashcards/audit/${documentId}/fill`, {
    method: "POST",
  })
  if (!res.ok) throw new Error("Failed to fill Bloom gaps")
  return res.json() as Promise<{ created: number }>
}

// S160: Deck health report API helpers
async function fetchDeckHealth(documentId: string): Promise<DeckHealthReport> {
  const res = await fetch(`${API_BASE}/flashcards/health/${documentId}`)
  if (!res.ok) throw new Error("Failed to load deck health report")
  return res.json() as Promise<DeckHealthReport>
}

async function archiveMastered(documentId: string): Promise<{ archived: number }> {
  const res = await fetch(
    `${API_BASE}/flashcards/health/${documentId}/archive-mastered`,
    { method: "POST" },
  )
  if (!res.ok) throw new Error("Failed to archive mastered cards")
  return res.json() as Promise<{ archived: number }>
}

async function fillUncovered(
  documentId: string,
  sectionIds: string[],
): Promise<{ queued: number }> {
  const res = await fetch(
    `${API_BASE}/flashcards/health/${documentId}/fill-uncovered`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section_ids: sectionIds }),
    },
  )
  if (!res.ok) throw new Error("Failed to queue uncovered section fill")
  return res.json() as Promise<{ queued: number }>
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

      {/* Footer: FSRS state badge + Bloom type/level badges */}
      <div className="flex items-center gap-2 border-t border-border pt-2 flex-wrap">
        <span className="rounded-full bg-secondary px-2 py-0.5 text-xs text-secondary-foreground capitalize">
          {card.fsrs_state}
        </span>
        {card.flashcard_type && (
          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-700 capitalize">
            {card.flashcard_type.replace(/_/g, " ")}
          </span>
        )}
        {card.bloom_level != null && (
          <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs text-purple-700">
            L{card.bloom_level}
          </span>
        )}
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
// FilterBar
// ---------------------------------------------------------------------------

const FLASHCARD_TYPE_OPTIONS = [
  "(All)",
  "cloze",  // S154: fill-in-the-blank
  "definition",
  "syntax_recall",
  "concept_explanation",
  "analogy",
  "code_completion",
  "api_signature",
  "trace",
  "pattern_recognition",
  "design_decision",
  "complexity",
  "implementation",
]

interface FilterBarProps {
  filterType: string | null
  filterBloomMin: number
  filterBloomMax: number
  onTypeChange: (v: string | null) => void
  onBloomMinChange: (v: number) => void
  onBloomMaxChange: (v: number) => void
  onClear: () => void
}

function FilterBar({
  filterType,
  filterBloomMin,
  filterBloomMax,
  onTypeChange,
  onBloomMinChange,
  onBloomMaxChange,
  onClear,
}: FilterBarProps) {
  const hasFilter = filterType !== null || filterBloomMin !== 1 || filterBloomMax !== 6
  return (
    <div className="flex flex-wrap items-end gap-3 rounded-md border border-border bg-muted/20 p-3">
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">Type</label>
        <select
          value={filterType ?? "(All)"}
          onChange={(e) => onTypeChange(e.target.value === "(All)" ? null : e.target.value)}
          className="rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        >
          {FLASHCARD_TYPE_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>{opt === "(All)" ? "All types" : opt.replace(/_/g, " ")}</option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">Bloom level (min)</label>
        <input
          type="number"
          min={1}
          max={6}
          value={filterBloomMin}
          onChange={(e) => onBloomMinChange(Math.min(Number(e.target.value), filterBloomMax))}
          className="w-16 rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">Bloom level (max)</label>
        <input
          type="number"
          min={1}
          max={6}
          value={filterBloomMax}
          onChange={(e) => onBloomMaxChange(Math.max(Number(e.target.value), filterBloomMin))}
          className="w-16 rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>
      {hasFilter && (
        <button
          onClick={onClear}
          className="rounded border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          Clear filters
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// DeckHealthPanel (S153) -- Bloom's taxonomy coverage audit
// ---------------------------------------------------------------------------

function coverageBadgeClass(score: number): string {
  if (score >= 0.7) return "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
  if (score >= 0.4) return "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200"
  return "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
}

function bloomBarFill(level: number): string {
  if (level <= 2) return "#94a3b8" // muted gray: remember/understand
  if (level <= 4) return "#3b82f6" // blue: apply/analyze
  return "#8b5cf6"                 // purple: evaluate/create
}

interface DeckHealthPanelProps {
  documentId: string
}

function DeckHealthPanel({ documentId }: DeckHealthPanelProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [gapsOpen, setGapsOpen] = useState(false)
  const qc = useQueryClient()

  const { data: report, isLoading, isError, refetch } = useQuery<CoverageReport, Error>({
    queryKey: ["audit", documentId],
    queryFn: () => fetchAudit(documentId),
    staleTime: 30_000,
    enabled: isOpen,
  })

  const fillMutation = useMutation({
    mutationFn: () => fillAuditGaps(documentId),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["audit", documentId] })
      toast.success(`Created ${data.created} new Bloom gap cards`)
    },
    onError: () => {
      toast.error("Failed to fill Bloom gaps")
    },
  })

  const chartData = report
    ? [1, 2, 3, 4, 5, 6].map((level) => ({
        name: `L${level}`,
        count: report.by_bloom_level[String(level)] ?? 0,
        fill: bloomBarFill(level),
      }))
    : []

  return (
    <section className="flex flex-col gap-2 rounded-md border border-border bg-card p-4">
      <button
        className="flex items-center justify-between text-left"
        onClick={() => setIsOpen((v) => !v)}
      >
        <span className="text-base font-semibold text-foreground">Deck Health</span>
        {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {isOpen && (
        <div className="flex flex-col gap-4 pt-2">
          {isLoading && (
            <div className="flex flex-col gap-2" aria-label="Loading deck health">
              {[40, 70, 55, 30, 20, 15].map((w, i) => (
                <div
                  key={i}
                  className="h-5 animate-pulse rounded bg-muted"
                  style={{ width: `${w}%` }}
                />
              ))}
            </div>
          )}

          {isError && (
            <div className="flex items-center gap-3 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
              <AlertCircle size={16} />
              <span>Could not load deck health</span>
              <button
                onClick={() => refetch()}
                className="ml-auto rounded border border-red-400 px-2 py-0.5 text-xs hover:bg-red-100 dark:hover:bg-red-900"
              >
                Retry
              </button>
            </div>
          )}

          {!isLoading && !isError && report && report.total_cards === 0 && (
            <p className="text-sm text-muted-foreground">
              No flashcards yet -- generate some to see Bloom distribution.
            </p>
          )}

          {!isLoading && !isError && report && report.total_cards > 0 && (
            <>
              <div className="flex items-center gap-3">
                <span className="text-sm text-muted-foreground">Coverage score</span>
                <span
                  className={`rounded px-2 py-0.5 text-xs font-semibold ${coverageBadgeClass(report.coverage_score)}`}
                >
                  {Math.round(report.coverage_score * 100)}%
                </span>
              </div>

              {/* Bloom level bar chart */}
              <div className="h-40 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                    <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                    <Tooltip formatter={(value: number | undefined) => [value ?? 0, "Cards"]} />
                    <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                      {chartData.map((entry, index) => (
                        <Cell key={`bar-${index}`} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Fill Gaps button */}
              {report.gaps.length > 0 && (
                <button
                  onClick={() => fillMutation.mutate()}
                  disabled={fillMutation.isPending}
                  className="flex items-center gap-2 self-start rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
                >
                  {fillMutation.isPending && <Loader2 size={14} className="animate-spin" />}
                  Fill Bloom Gaps
                </button>
              )}

              {/* Per-section gap list */}
              {report.gaps.length > 0 && (
                <div className="flex flex-col gap-1">
                  <button
                    className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                    onClick={() => setGapsOpen((v) => !v)}
                  >
                    {gapsOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                    {report.gaps.length} section{report.gaps.length > 1 ? "s" : ""} missing L3+ cards
                  </button>
                  {gapsOpen && (
                    <ul className="ml-4 flex flex-col gap-1">
                      {report.gaps.map((gap) => (
                        <li key={gap.section_id} className="text-xs text-muted-foreground">
                          <span className="font-medium text-foreground">{gap.section_heading}</span>
                          {" — missing L"}
                          {gap.missing_bloom_levels.join(", L")}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {report.gaps.length === 0 && (
                <p className="text-xs text-green-700 dark:text-green-400">
                  All sections have L3+ cards -- good coverage!
                </p>
              )}
            </>
          )}
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// HealthReportPanel (S160) -- orphaned/mastered/stale/uncovered/hotspot metrics
// ---------------------------------------------------------------------------

interface HealthReportPanelProps {
  documentId: string
}

function HealthReportPanel({ documentId }: HealthReportPanelProps) {
  const [isOpen, setIsOpen] = useState(false)
  const qc = useQueryClient()

  const { data: report, isLoading, isError, refetch } = useQuery<DeckHealthReport, Error>({
    queryKey: ["health", documentId],
    queryFn: () => fetchDeckHealth(documentId),
    staleTime: 300_000,
    enabled: isOpen,
  })

  const archiveMutation = useMutation({
    mutationFn: () => archiveMastered(documentId),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["health", documentId] })
      qc.invalidateQueries({ queryKey: ["flashcards", documentId] })
      toast.success(`Archived ${data.archived} mastered cards`)
    },
    onError: () => {
      toast.error("Failed to archive mastered cards")
    },
  })

  const fillMutation = useMutation({
    mutationFn: () =>
      fillUncovered(documentId, report?.uncovered_section_ids ?? []),
    onSuccess: (data) => {
      toast.success(
        `Generating cards for ${data.queued} uncovered sections in background`,
      )
    },
    onError: () => {
      toast.error("Failed to queue uncovered section fill")
    },
  })

  const totalCards =
    (report?.orphaned ?? 0) +
    (report?.mastered ?? 0) +
    (report?.stale ?? 0)

  return (
    <section className="flex flex-col gap-2 rounded-md border border-border bg-card p-4">
      <button
        className="flex items-center justify-between text-left"
        onClick={() => setIsOpen((v) => !v)}
      >
        <span className="text-base font-semibold text-foreground">
          Health Report
        </span>
        {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {isOpen && (
        <div className="flex flex-col gap-4 pt-2">
          {isLoading && (
            <div
              className="flex flex-col gap-2"
              aria-label="Loading health report"
            >
              {[60, 80, 50, 70, 40].map((w, i) => (
                <div
                  key={i}
                  className="h-8 animate-pulse rounded bg-muted"
                  style={{ width: `${w}%` }}
                />
              ))}
            </div>
          )}

          {isError && (
            <div className="flex items-center gap-3 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
              <AlertCircle size={16} />
              <span>Could not load health report</span>
              <button
                onClick={() => refetch()}
                className="ml-auto rounded border border-red-400 px-2 py-0.5 text-xs hover:bg-red-100 dark:hover:bg-red-900"
              >
                Retry
              </button>
            </div>
          )}

          {!isLoading && !isError && report && totalCards === 0 && report.uncovered_sections === 0 && report.hotspot_sections.length === 0 && (
            <div className="flex items-center gap-2 text-sm text-green-700 dark:text-green-400">
              <Check size={16} />
              <span>Deck is healthy -- no issues found</span>
            </div>
          )}

          {!isLoading && !isError && report && (
            <>
              {/* 5 metric pills */}
              <div className="flex flex-wrap gap-2">
                {/* Orphaned */}
                <div
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
                    report.orphaned > 0
                      ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
                      : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                  }`}
                >
                  <span className="font-bold">{report.orphaned}</span>
                  <span>orphaned</span>
                </div>

                {/* Mastered */}
                <div className="flex items-center gap-1.5 rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                  <span className="font-bold">{report.mastered}</span>
                  <span>mastered</span>
                </div>

                {/* Stale */}
                <div
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
                    report.stale > 0
                      ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
                      : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                  }`}
                >
                  <span className="font-bold">{report.stale}</span>
                  <span>stale</span>
                </div>

                {/* Uncovered sections */}
                <div
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
                    report.uncovered_sections > 0
                      ? "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
                      : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                  }`}
                >
                  <span className="font-bold">{report.uncovered_sections}</span>
                  <span>uncovered</span>
                </div>

                {/* Hotspot */}
                <div className="flex items-center gap-1.5 rounded-full bg-purple-100 px-3 py-1 text-xs font-medium text-purple-800 dark:bg-purple-900 dark:text-purple-200">
                  <span className="font-bold">
                    {report.hotspot_sections.length > 0
                      ? report.hotspot_sections[0].section_heading
                      : "--"}
                  </span>
                  <span>hotspot</span>
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex flex-wrap gap-2">
                {report.mastered > 0 && (
                  <button
                    onClick={() => archiveMutation.mutate()}
                    disabled={archiveMutation.isPending}
                    className="flex items-center gap-2 rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
                  >
                    {archiveMutation.isPending && (
                      <Loader2 size={14} className="animate-spin" />
                    )}
                    Archive {report.mastered} mastered
                  </button>
                )}

                {report.uncovered_sections > 0 && (
                  <button
                    onClick={() => fillMutation.mutate()}
                    disabled={fillMutation.isPending}
                    className="flex items-center gap-2 rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
                  >
                    {fillMutation.isPending && (
                      <Loader2 size={14} className="animate-spin" />
                    )}
                    Generate for {report.uncovered_sections} uncovered sections
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </section>
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
// DeckStatusAccordion (S178) -- merged DeckHealthPanel + HealthReportPanel
// ---------------------------------------------------------------------------

interface DeckStatusAccordionProps {
  documentId: string
  cards: Flashcard[]
}

function DeckStatusAccordion({ documentId, cards }: DeckStatusAccordionProps) {
  const [isOpen, setIsOpen] = useState(false)
  const totalCards = cards.length
  const masteredPct = Math.round(computeMasteryPct(cards))

  return (
    <section className="flex flex-col gap-2 rounded-md border border-border bg-card p-4">
      <button
        className="flex items-center justify-between text-left"
        onClick={() => setIsOpen((v) => !v)}
      >
        <span className="text-base font-semibold text-foreground">
          Deck Status ({totalCards} card{totalCards !== 1 ? "s" : ""}, {masteredPct}% mastered)
        </span>
        {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {isOpen && (
        <div className="flex flex-col gap-4 pt-2">
          <DeckHealthPanel documentId={documentId} />
          <HealthReportPanel documentId={documentId} />
        </div>
      )}
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
  onGenerateFromGraph: (k: number) => void
  // S154: cloze generation (section-scoped)
  onGenerateCloze: (sectionId: string, count: number) => void
  isGenerating: boolean
  isClozeGenerating: boolean
  preselectedSection?: string | null
}

const COUNT_OPTIONS = [5, 10, 20, 50]
const DIFFICULTY_OPTIONS = [
  { value: "easy", label: "Easy" },
  { value: "medium", label: "Medium" },
  { value: "hard", label: "Hard" },
]

const PAIRS_K_OPTIONS = [3, 5, 10]

function GeneratePanel({
  documentId,
  sections,
  onGenerate,
  onRegenerate,
  onGenerateFromGraph,
  onGenerateCloze,
  isGenerating,
  isClozeGenerating,
  preselectedSection,
}: GeneratePanelProps) {
  const [mode, setMode] = useState<"text" | "entities" | "cloze">("text")
  const [count, setCount] = useState(10)
  const [scope, setScope] = useState<"full" | "section">("full")
  const [sectionHeading, setSectionHeading] = useState<string | null>(null)
  const [difficulty, setDifficulty] = useState<"easy" | "medium" | "hard">("medium")
  const [pairsK, setPairsK] = useState(5)
  // S154: cloze tab state
  const [clozeSectionId, setClozeSectionId] = useState<string | null>(null)
  const [clozeCount, setClozeCount] = useState(5)

  // Sync scope/heading when a gap section is clicked from outside
  useEffect(() => {
    if (preselectedSection != null) {
      setScope("section")
      setSectionHeading(preselectedSection)
    }
  }, [preselectedSection])

  const {
    data: pairsData,
    isLoading: pairsLoading,
    isError: pairsError,
  } = useQuery<EntityPairsResponse>({
    queryKey: ["entity-pairs", documentId],
    queryFn: () => fetchEntityPairs(documentId),
    enabled: mode === "entities",
    staleTime: 60_000,
  })
  const entityPairs = pairsData?.pairs ?? []

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-muted/30 p-4">
      {/* Mode toggle */}
      <div className="flex gap-0 rounded-md border border-border bg-background w-fit">
        <button
          onClick={() => setMode("text")}
          className={`px-3 py-1.5 text-sm font-medium rounded-l-md transition-colors ${
            mode === "text"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          From Text
        </button>
        <button
          onClick={() => setMode("entities")}
          className={`px-3 py-1.5 text-sm font-medium transition-colors ${
            mode === "entities"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          From Entities
        </button>
        <button
          onClick={() => setMode("cloze")}
          className={`px-3 py-1.5 text-sm font-medium rounded-r-md transition-colors ${
            mode === "cloze"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Cloze
        </button>
      </div>

      {mode === "text" ? (
        <div className="flex flex-wrap items-end gap-3">
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
      ) : mode === "entities" ? (
        <div className="flex flex-col gap-4">
          {/* Top pairs count */}
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground">Top pairs</label>
              <select
                value={pairsK}
                onChange={(e) => setPairsK(Number(e.target.value))}
                className="rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {PAIRS_K_OPTIONS.map((n) => (
                  <option key={n} value={n}>
                    {n} pairs
                  </option>
                ))}
              </select>
            </div>
            <button
              onClick={() => onGenerateFromGraph(pairsK)}
              disabled={isGenerating}
              className="flex items-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {isGenerating && <Loader2 size={14} className="animate-spin" />}
              Generate from Entities
            </button>
          </div>

          {/* Entity pairs preview */}
          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium text-muted-foreground">Entity pair preview</span>
            {pairsLoading ? (
              <div className="flex items-center gap-2 py-3 text-sm text-muted-foreground">
                <Loader2 size={14} className="animate-spin" />
                Loading entity pairs...
              </div>
            ) : pairsError ? (
              <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                Could not load entity pairs.
              </div>
            ) : entityPairs.length === 0 ? (
              <div className="rounded border border-border bg-muted/20 px-3 py-3 text-sm text-muted-foreground">
                No entity relationships found for this document. Try ingesting the document first.
              </div>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {entityPairs.map((pair, i) => (
                  <li
                    key={i}
                    className="flex items-center gap-2 rounded border border-border bg-background px-3 py-2 text-sm"
                  >
                    <span className="font-medium text-foreground">{pair.name_a}</span>
                    <span className="text-muted-foreground">--</span>
                    <span className="italic text-muted-foreground">{pair.relation_label}</span>
                    <span className="text-muted-foreground">--</span>
                    <span className="font-medium text-foreground">{pair.name_b}</span>
                    <span className="ml-auto rounded-full bg-secondary px-2 py-0.5 text-xs text-secondary-foreground">
                      {Math.round(pair.confidence * 100)}%
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : mode === "cloze" ? (
        /* S154: Cloze (fill-in-the-blank) generation tab */
        <div className="flex flex-wrap items-end gap-3">
          {/* Section picker — required for cloze (endpoint is section-scoped) */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground">
              Section <span className="text-red-500">*</span>
            </label>
            <select
              value={clozeSectionId ?? ""}
              onChange={(e) => setClozeSectionId(e.target.value || null)}
              className="max-w-[240px] rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">Select a section...</option>
              {sections.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.heading}
                </option>
              ))}
            </select>
            {!clozeSectionId && (
              <span className="text-xs text-muted-foreground">Select a section to generate cloze cards.</span>
            )}
          </div>

          {/* Count */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground">Count</label>
            <select
              value={clozeCount}
              onChange={(e) => setClozeCount(Number(e.target.value))}
              className="rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {COUNT_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n} cards
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={() => clozeSectionId && onGenerateCloze(clozeSectionId, clozeCount)}
            disabled={isClozeGenerating || !clozeSectionId}
            className="flex items-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {isClozeGenerating && <Loader2 size={14} className="animate-spin" />}
            Generate Cloze Cards
          </button>
        </div>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// SmartGeneratePanel (S178) -- single Smart Generate button with advanced options
// ---------------------------------------------------------------------------

const SMART_MODE_LABEL: Record<string, string> = {
  basic: "basic cards",
  feynman: "Feynman-style questions",
  cloze: "cloze cards",
}

const SMART_MODE_HINT: Record<string, string> = {
  basic: "Building foundations (< 30% mastered)",
  feynman: "Deepening comprehension (30-70% mastered)",
  cloze: "Retrieval practice (>= 70% mastered)",
}

interface SmartGeneratePanelProps {
  documentId: string
  sections: SectionItem[]
  cards: Flashcard[]
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
  onGenerateFromGraph: (k: number) => void
  onGenerateCloze: (sectionId: string, count: number) => void
  isGenerating: boolean
  isClozeGenerating: boolean
  preselectedSection?: string | null
}

function SmartGeneratePanel({
  documentId,
  sections,
  cards,
  onGenerate,
  onRegenerate,
  onGenerateFromGraph,
  onGenerateCloze,
  isGenerating,
  isClozeGenerating,
  preselectedSection,
}: SmartGeneratePanelProps) {
  const masteryPct = computeMasteryPct(cards)
  const smartMode = selectSmartMode(masteryPct)
  const isAnyGenerating = isGenerating || isClozeGenerating

  function handleSmartGenerate() {
    if (smartMode === "feynman") {
      onGenerateFromGraph(5)
    } else if (smartMode === "cloze") {
      const firstSection = sections[0]
      if (firstSection) {
        onGenerateCloze(firstSection.id, 5)
      } else {
        // no sections available -- fall back to basic
        onGenerate({ scope: "full", section_heading: null, count: 10, difficulty: "medium" })
      }
    } else {
      onGenerate({ scope: "full", section_heading: null, count: 10, difficulty: "medium" })
    }
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-muted/30 p-4">
      {/* Smart Generate button */}
      <div className="flex flex-col gap-1.5">
        <button
          onClick={handleSmartGenerate}
          disabled={isAnyGenerating}
          className="flex w-fit items-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {isAnyGenerating ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Zap size={14} />
          )}
          Smart Generate
        </button>
        <span className="text-xs text-muted-foreground">
          {isAnyGenerating
            ? `Generating ${SMART_MODE_LABEL[smartMode]}...`
            : SMART_MODE_HINT[smartMode]}
        </span>
      </div>

      {/* Advanced options disclosure */}
      <details>
        <summary className="cursor-pointer select-none text-sm text-muted-foreground hover:text-foreground">
          Advanced options
        </summary>
        <div className="pt-3">
          <GeneratePanel
            documentId={documentId}
            sections={sections}
            onGenerate={onGenerate}
            onRegenerate={onRegenerate}
            onGenerateFromGraph={onGenerateFromGraph}
            onGenerateCloze={onGenerateCloze}
            isGenerating={isGenerating}
            isClozeGenerating={isClozeGenerating}
            preselectedSection={preselectedSection}
          />
        </div>
      </details>
    </div>
  )
}

// ---------------------------------------------------------------------------
// StrugglingPanel
// ---------------------------------------------------------------------------

interface StrugglingPanelProps {
  documentId: string
}

function StrugglingPanel({ documentId }: StrugglingPanelProps) {
  const navigate = useNavigate()
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)

  const { data: cards = [], isLoading, isError } = useQuery<StrugglingCard[], Error>({
    queryKey: ["struggling", documentId],
    queryFn: () => fetchStrugglingCards(documentId),
    enabled: !!documentId,
  })

  function handleReread(card: StrugglingCard) {
    if (!card.document_id) return
    setActiveDocument(card.document_id)
    if (card.source_section_id) {
      void navigate(`/?section_id=${encodeURIComponent(card.source_section_id)}`)
    } else {
      void navigate("/")
    }
  }

  if (!documentId) return null

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold text-foreground">Struggling Cards</h2>

      {isLoading ? (
        <div className="flex flex-col gap-2">
          {[0, 1].map((i) => (
            <div key={i} className="h-16 animate-pulse rounded-md bg-muted" />
          ))}
        </div>
      ) : isError ? (
        <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle size={14} />
          Failed to load struggling cards. Please try refreshing.
        </div>
      ) : cards.length === 0 ? (
        <p className="py-4 text-center text-sm text-muted-foreground">
          No struggling cards in the last 14 days.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {cards.map((card) => (
            <div
              key={card.flashcard_id}
              className="flex items-start justify-between gap-3 rounded-md border border-border bg-card px-4 py-3"
            >
              <div className="flex flex-col gap-1 flex-1 min-w-0">
                <p className="truncate text-sm text-foreground">{card.question}</p>
                <span className="inline-flex w-fit items-center gap-1 rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                  {card.again_count}x Again
                </span>
              </div>
              {card.source_section_id && (
                <button
                  onClick={() => handleReread(card)}
                  className="flex-shrink-0 flex items-center gap-1.5 rounded border border-border px-3 py-1 text-xs text-foreground hover:bg-accent"
                >
                  <BookOpen size={12} />
                  Re-read source
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// GoalsPanel (exported so Progress tab can render it without Study tab re-implementing)
// ---------------------------------------------------------------------------

export { fetchGoals, createGoal, deleteGoalApi, fetchReadiness }
export type { LearningGoal, ReadinessResult, AtRiskCard, DocListItem }

function RetentionBadge({ pct }: { pct: number }) {
  const color =
    pct >= 80
      ? "bg-green-100 text-green-800 border-green-200"
      : pct >= 60
        ? "bg-yellow-100 text-yellow-800 border-yellow-200"
        : "bg-red-100 text-red-800 border-red-200"
  return (
    <span className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium ${color}`}>
      {pct.toFixed(1)}% projected retention
    </span>
  )
}

interface GoalRowProps {
  goal: LearningGoal
  docTitle: string
  onDelete: (id: string) => void
  isDeleting: boolean
}

function GoalRow({ goal, docTitle, onDelete, isDeleting }: GoalRowProps) {
  const readinessQuery = useQuery<ReadinessResult, Error>({
    queryKey: ["goal-readiness", goal.id],
    queryFn: () => fetchReadiness(goal.id),
    enabled: false,
  })

  function handleCheckReadiness() {
    void readinessQuery.refetch()
  }

  return (
    <div className="rounded-md border border-border bg-card p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <span className="text-sm font-medium text-foreground">{goal.title}</span>
          <span className="text-xs text-muted-foreground">
            {docTitle} &middot; by {goal.target_date}
          </span>
        </div>
        <button
          onClick={() => onDelete(goal.id)}
          disabled={isDeleting}
          className="flex-shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
          aria-label="Delete goal"
        >
          <Trash2 size={14} />
        </button>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={handleCheckReadiness}
          disabled={readinessQuery.isFetching}
          className="flex items-center gap-1.5 rounded border border-border px-3 py-1 text-xs text-foreground hover:bg-accent disabled:opacity-50"
        >
          {readinessQuery.isFetching ? <Loader2 size={12} className="animate-spin" /> : <CalendarDays size={12} />}
          Check Readiness
        </button>

        {readinessQuery.isError && (
          <span className="flex items-center gap-1 text-xs text-red-600">
            <AlertCircle size={12} />
            Failed to compute readiness
          </span>
        )}
        {readinessQuery.data && <RetentionBadge pct={readinessQuery.data.projected_retention_pct} />}
      </div>

      {readinessQuery.data && readinessQuery.data.at_risk_card_count > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            {readinessQuery.data.at_risk_card_count} at-risk card{readinessQuery.data.at_risk_card_count !== 1 ? "s" : ""}
          </span>
          <ul className="flex flex-col gap-1">
            {readinessQuery.data.at_risk_cards.slice(0, 5).map((c) => (
              <li key={c.id} className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="truncate flex-1">{c.question}</span>
                <span className="flex-shrink-0 text-red-600">{c.projected_retention_pct.toFixed(0)}%</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {readinessQuery.data && readinessQuery.data.at_risk_card_count === 0 && (
        <p className="text-xs text-green-700">All cards on track for this goal.</p>
      )}
    </div>
  )
}

export interface GoalsPanelProps {
  docs: DocListItem[]
}

export function GoalsPanel({ docs }: GoalsPanelProps) {
  const qc = useQueryClient()
  const [title, setTitle] = useState("")
  const [docId, setDocId] = useState("")
  const [targetDate, setTargetDate] = useState("")
  const [formError, setFormError] = useState<string | null>(null)

  const goalsQuery = useQuery<LearningGoal[], Error>({
    queryKey: ["goals"],
    queryFn: fetchGoals,
  })

  const createMutation = useMutation({
    mutationFn: createGoal,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["goals"] })
      setTitle("")
      setDocId("")
      setTargetDate("")
      setFormError(null)
    },
    onError: () => setFormError("Failed to create goal. Please try again."),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteGoalApi,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["goals"] })
    },
    onError: () => toast.error("Failed to delete goal"),
  })

  function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    if (!title.trim()) return setFormError("Title is required")
    if (!docId) return setFormError("Select a document")
    if (!targetDate) return setFormError("Pick a target date")
    createMutation.mutate({ document_id: docId, title: title.trim(), target_date: targetDate })
  }

  const docMap = new Map(docs.map((d) => [d.id, d.title]))

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold text-foreground">Learning Goals</h2>

      {/* Creation form */}
      <form onSubmit={handleCreate} className="flex flex-col gap-3 rounded-md border border-border bg-muted/30 p-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:gap-3">
          <div className="flex flex-col gap-1 flex-1">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="goal-title">
              Goal title
            </label>
            <input
              id="goal-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder='e.g. "Master The Time Machine"'
              className="rounded border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="goal-doc">
              Document
            </label>
            <select
              id="goal-doc"
              value={docId}
              onChange={(e) => setDocId(e.target.value)}
              className="rounded border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            >
              <option value="">Select document</option>
              {docs.map((d) => (
                <option key={d.id} value={d.id}>{d.title}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="goal-date">
              Target date
            </label>
            <input
              id="goal-date"
              type="date"
              value={targetDate}
              onChange={(e) => setTargetDate(e.target.value)}
              className="rounded border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="flex items-center gap-2 rounded bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {createMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            Add Goal
          </button>
        </div>
        {formError && (
          <p className="flex items-center gap-1 text-xs text-red-600">
            <AlertCircle size={12} />
            {formError}
          </p>
        )}
      </form>

      {/* Goal list */}
      {goalsQuery.isLoading ? (
        <div className="flex flex-col gap-2">
          {[0, 1].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-md bg-muted" />
          ))}
        </div>
      ) : goalsQuery.isError ? (
        <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle size={14} />
          Failed to load goals. Please try refreshing.
        </div>
      ) : goalsQuery.data && goalsQuery.data.length === 0 ? (
        <p className="py-4 text-center text-sm text-muted-foreground">
          No goals yet. Add one above.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {goalsQuery.data?.map((goal) => (
            <GoalRow
              key={goal.id}
              goal={goal}
              docTitle={docMap.get(goal.document_id) ?? goal.document_id}
              onDelete={(id) => deleteMutation.mutate(id)}
              isDeleting={deleteMutation.isPending}
            />
          ))}
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// SessionHistoryTab
// ---------------------------------------------------------------------------

function SessionHistoryTab() {
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 20
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null)

  const { data, isLoading, isError } = useQuery<SessionListResponse, Error>({
    queryKey: ["study-sessions", page],
    queryFn: () => fetchSessions(page, PAGE_SIZE),
  })

  const { data: sessionCards, isLoading: cardsLoading, isError: cardsError } = useQuery<SessionCardDetail[], Error>({
    queryKey: ["session-cards", expandedSessionId],
    queryFn: () => fetchSessionCards(expandedSessionId!),
    enabled: expandedSessionId !== null,
  })

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 1

  function formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  function formatDuration(mins: number | null): string {
    if (mins === null) return "-"
    if (mins < 1) return "< 1 min"
    return `${Math.round(mins)} min`
  }

  function formatAccuracy(pct: number | null): string {
    return pct !== null ? `${pct}%` : "-"
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {[1, 2, 3].map((n) => (
          <div key={n} className="h-10 animate-pulse rounded-md bg-muted" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        Failed to load session history. Please try refreshing.
      </div>
    )
  }

  if (!data || data.items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <p className="text-sm text-muted-foreground">
          No study sessions recorded yet. Complete a session to see history here.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/50 text-left text-xs text-muted-foreground">
              <th className="px-4 py-2 font-medium">Date</th>
              <th className="px-4 py-2 font-medium">Duration</th>
              <th className="px-4 py-2 font-medium">Cards</th>
              <th className="px-4 py-2 font-medium">Accuracy</th>
              <th className="px-4 py-2 font-medium">Document</th>
              <th className="px-4 py-2 font-medium">Mode</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((sess) => (
              <Fragment key={sess.id}>
                <tr
                  className="cursor-pointer border-b border-border hover:bg-accent/30"
                  onClick={() =>
                    setExpandedSessionId(expandedSessionId === sess.id ? null : sess.id)
                  }
                >
                  <td className="px-4 py-2 text-foreground">{formatDate(sess.started_at)}</td>
                  <td className="px-4 py-2 text-muted-foreground">{formatDuration(sess.duration_minutes)}</td>
                  <td className="px-4 py-2 text-muted-foreground">{sess.cards_reviewed}</td>
                  <td className="px-4 py-2 text-muted-foreground">{formatAccuracy(sess.accuracy_pct)}</td>
                  <td className="px-4 py-2 text-muted-foreground">{sess.document_title ?? "-"}</td>
                  <td className="px-4 py-2 text-muted-foreground">{sess.mode}</td>
                </tr>
                {expandedSessionId === sess.id && (
                  <tr key={`${sess.id}-detail`} className="border-b border-border bg-muted/20">
                    <td colSpan={6} className="px-4 py-3">
                      {cardsLoading ? (
                        <div className="flex flex-col gap-1">
                          {[1, 2].map((n) => (
                            <div key={n} className="h-8 animate-pulse rounded bg-muted" />
                          ))}
                        </div>
                      ) : cardsError ? (
                        <p className="text-sm text-red-600">Failed to load card details.</p>
                      ) : !sessionCards || sessionCards.length === 0 ? (
                        <p className="text-sm text-muted-foreground">No card events recorded for this session.</p>
                      ) : (
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-left text-muted-foreground">
                              <th className="pb-1 pr-4 font-medium">Question</th>
                              <th className="pb-1 pr-4 font-medium">Rating</th>
                              <th className="pb-1 font-medium">Result</th>
                            </tr>
                          </thead>
                          <tbody>
                            {sessionCards.map((card) => (
                              <tr key={card.flashcard_id} className="border-t border-border/50">
                                <td className="py-1 pr-4 max-w-xs truncate text-foreground">
                                  {card.question}
                                </td>
                                <td className="py-1 pr-4 text-muted-foreground capitalize">{card.rating}</td>
                                <td className="py-1">
                                  {card.is_correct ? (
                                    <span className="text-green-600">Correct</span>
                                  ) : (
                                    <span className="text-red-500">Incorrect</span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="rounded border border-border px-3 py-1 hover:bg-accent disabled:opacity-40"
          >
            Previous
          </button>
          <span>Page {page} of {totalPages}</span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="rounded border border-border px-3 py-1 hover:bg-accent disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
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
  const studySectionFilter = useAppStore((s) => s.studySectionFilter)
  const setStudySectionFilter = useAppStore((s) => s.setStudySectionFilter)
  const queryClient = useQueryClient()
  const [studying, setStudying] = useState(false)
  // Track section pre-selected by clicking a gap item
  const [selectedGapSection, setSelectedGapSection] = useState<string | null>(null)
  const [generateErrorKind, setGenerateErrorKind] = useState<GenerateErrorKind>(null)
  const [studySubTab, setStudySubTab] = useState<"flashcards" | "history">("flashcards")
  const [filterType, setFilterType] = useState<string | null>(null)
  const [filterBloomMin, setFilterBloomMin] = useState(1)
  const [filterBloomMax, setFilterBloomMax] = useState(6)
  // S143: active section filter consumed from store
  const [activeSectionFilter, setActiveSectionFilter] = useState<{
    sectionId: string
    bloomLevelMin: number
    sectionHeading?: string
  } | null>(null)
  const mountTime = useRef(Date.now())

  // Document list for the in-tab picker
  const { data: docList = [] } = useQuery<DocListItem[]>({
    queryKey: ["study-doc-list"],
    queryFn: fetchDocList,
    staleTime: 30_000,
  })

  // S169: All decks list
  const { data: deckList = [] } = useQuery<DeckItem[]>({
    queryKey: ["flashcard-decks"],
    queryFn: fetchDecks,
    staleTime: 60_000,
  })

  useEffect(() => {
    logger.info("[Study] mounted")
  }, [])

  // S143: consume studySectionFilter from store when it changes
  useEffect(() => {
    if (!studySectionFilter) return
    setActiveSectionFilter({
      sectionId: studySectionFilter.sectionId,
      bloomLevelMin: studySectionFilter.bloomLevelMin,
    })
    // Clear the store filter immediately after consuming
    setStudySectionFilter(null)
  }, [studySectionFilter, setStudySectionFilter])

  // Flashcard list — include section/bloom filters when set (S143)
  const { data: cards = [], isLoading: cardsLoading, isError: cardsError } = useQuery<Flashcard[]>({
    queryKey: ["flashcards", activeDocumentId, activeSectionFilter?.sectionId, activeSectionFilter?.bloomLevelMin],
    queryFn: () => fetchFlashcards(
      activeDocumentId!,
      activeSectionFilter?.sectionId,
      activeSectionFilter?.bloomLevelMin,
    ),
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

  // Generate from graph mutation
  const generateFromGraphMutation = useMutation({
    mutationFn: (k: number) =>
      generateFromGraph({ document_id: activeDocumentId!, k }),
    onSuccess: (newCards) => {
      setGenerateErrorKind(null)
      void queryClient.invalidateQueries({ queryKey: ["flashcards", activeDocumentId] })
      toast.success(
        `Generated ${newCards.length} flashcard${newCards.length !== 1 ? "s" : ""} from entity pairs`
      )
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

  // S154: Cloze generation mutation
  const generateClozeMutation = useMutation({
    mutationFn: ({ sectionId, count }: { sectionId: string; count: number }) =>
      generateClozeFlashcards(sectionId, count),
    onSuccess: (newCards) => {
      setGenerateErrorKind(null)
      void queryClient.invalidateQueries({ queryKey: ["flashcards", activeDocumentId] })
      toast.success(`Generated ${newCards.length} cloze card${newCards.length !== 1 ? "s" : ""}`)
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
          if (activeDocumentId) {
            void queryClient.invalidateQueries({ queryKey: ["section-heatmap", activeDocumentId] })
          }
        }}
      />
    )
  }

  return (
    <div className="flex h-full flex-col gap-6 overflow-auto p-6">
      {/* S169: All Decks panel */}
      {deckList.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-foreground">All Decks</h2>
          <div className="flex flex-col divide-y divide-border rounded-lg border border-border bg-card">
            {(() => {
              // S178: compute per-document deck count for getDeckDisplayName alias
              const decksPerDoc = new Map<string, number>()
              deckList.forEach((d) => {
                if (d.document_id) decksPerDoc.set(d.document_id, (decksPerDoc.get(d.document_id) ?? 0) + 1)
              })
              return deckList.map((deck) => (
              <div key={deck.deck} className="flex items-center gap-3 px-4 py-2.5">
                {deck.source_type === "collection" ? (
                  <Folder size={16} className="shrink-0 text-indigo-500" />
                ) : (
                  <BookOpen size={16} className="shrink-0 text-slate-500" />
                )}
                <span className="flex-1 text-sm font-medium text-foreground truncate">
                  {getDeckDisplayName({
                    deckName: deck.deck,
                    documentId: deck.document_id,
                    docTitle: docList.find((d) => d.id === deck.document_id)?.title,
                    isOnlyDeckForDocument: (decksPerDoc.get(deck.document_id ?? "") ?? 0) === 1,
                  })}
                </span>
                <span className="text-xs text-muted-foreground">{deck.card_count} cards</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    deck.source_type === "collection"
                      ? "bg-indigo-100 text-indigo-700"
                      : "bg-slate-100 text-slate-600"
                  }`}
                >
                  {deck.source_type}
                </span>
              </div>
            ))
            })()}
          </div>
        </section>
      )}

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
      {/* Sub-tab toggle */}
      <div className="flex gap-1 rounded-lg border border-border bg-muted/40 p-1 w-fit">
        <button
          onClick={() => setStudySubTab("flashcards")}
          className={`rounded px-4 py-1.5 text-sm font-medium transition-colors ${
            studySubTab === "flashcards"
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Flashcards
        </button>
        <button
          onClick={() => setStudySubTab("history")}
          className={`rounded px-4 py-1.5 text-sm font-medium transition-colors ${
            studySubTab === "history"
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          History
        </button>
      </div>

      {studySubTab === "history" ? (
        <section className="flex flex-col gap-4">
          <h2 className="text-lg font-semibold text-foreground">Session History</h2>
          <SessionHistoryTab />
        </section>
      ) : (
      <>
      {/* S143: Section filter banner */}
      {activeSectionFilter && (
        <div className="flex items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm">
          <span className="text-foreground">
            Showing flashcards for section &mdash; bloom level &ge; {activeSectionFilter.bloomLevelMin}
          </span>
          <button
            onClick={() => setActiveSectionFilter(null)}
            className="ml-auto shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground"
            title="Clear section filter"
          >
            <X size={14} />
          </button>
        </div>
      )}
      {/* Flashcards section */}
      <section className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold text-foreground">Flashcards</h2>

        <SmartGeneratePanel
          documentId={activeDocumentId}
          sections={sections}
          cards={cards}
          onGenerate={(req) => { setGenerateErrorKind(null); generateMutation.mutate(req) }}
          onRegenerate={handleRegenerate}
          onGenerateFromGraph={(k) => {
            setGenerateErrorKind(null)
            generateFromGraphMutation.mutate(k)
          }}
          onGenerateCloze={(sectionId, count) => {
            setGenerateErrorKind(null)
            generateClozeMutation.mutate({ sectionId, count })
          }}
          isGenerating={
            generateMutation.isPending ||
            deleteAllMutation.isPending ||
            generateFromGraphMutation.isPending
          }
          isClozeGenerating={generateClozeMutation.isPending}
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

        {/* Filter bar — only shown when there are cards with type/level data */}
        {cards.length > 0 && (
          <FilterBar
            filterType={filterType}
            filterBloomMin={filterBloomMin}
            filterBloomMax={filterBloomMax}
            onTypeChange={setFilterType}
            onBloomMinChange={setFilterBloomMin}
            onBloomMaxChange={setFilterBloomMax}
            onClear={() => { setFilterType(null); setFilterBloomMin(1); setFilterBloomMax(6) }}
          />
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
              No flashcards yet -- click Smart Generate to create some
            </p>
          </div>
        ) : (() => {
          const filteredCards = cards.filter((c) => {
            const typeMatch = filterType === null || c.flashcard_type === filterType
            const bloomMatch =
              c.bloom_level == null ||
              (c.bloom_level >= filterBloomMin && c.bloom_level <= filterBloomMax)
            return typeMatch && bloomMatch
          })
          if (filteredCards.length === 0) {
            return (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <p className="text-sm text-muted-foreground">
                  No cards match the selected type/level filters. Try adjusting the filter.
                </p>
              </div>
            )
          }
          return (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {filteredCards.map((card) => (
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
          )
        })()}

        {/* Bottom bar */}
        {cards.length > 0 && (
          <div className="flex items-center gap-3 border-t border-border pt-4">
            <span className="text-sm text-muted-foreground">
              {(() => {
                const filteredCount = cards.filter((c) => {
                  const typeMatch = filterType === null || c.flashcard_type === filterType
                  const bloomMatch =
                    c.bloom_level == null ||
                    (c.bloom_level >= filterBloomMin && c.bloom_level <= filterBloomMax)
                  return typeMatch && bloomMatch
                }).length
                const total = cards.length
                return filteredCount === total
                  ? `${total} card${total !== 1 ? "s" : ""}`
                  : `${filteredCount} of ${total} card${total !== 1 ? "s" : ""}`
              })()}
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

      {/* Deck Status accordion (S178) -- merged Bloom audit + health report, collapsed by default */}
      <DeckStatusAccordion documentId={activeDocumentId} cards={cards} />

      {/* Weak Areas panel */}
      <WeakAreasPanel
        documentId={activeDocumentId}
        onSelectSection={(heading) => {
          setSelectedGapSection(heading)
          // Scroll to top to reveal pre-scoped SmartGeneratePanel
          window.scrollTo({ top: 0, behavior: "smooth" })
        }}
      />

      {/* Struggling Cards panel */}
      <StrugglingPanel documentId={activeDocumentId} />

      {/* Progress dashboard (S23b) — Recharts loaded lazily via dynamic import */}
      <section className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold text-foreground">Progress</h2>
        <Suspense fallback={<div className="h-48 animate-pulse rounded-md bg-muted" />}>
          <ProgressDashboard documentId={activeDocumentId} />
        </Suspense>
      </section>
      </>
      )}
      </>
      )}
    </div>
  )
}
