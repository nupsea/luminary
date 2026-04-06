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
  BLOOM_LEVEL_LABELS,
  FSRS_STATE_LABELS,
  INSIGHTS_SECTIONS,
  buildSearchParams,
  buildSmartGenerateParams,
  computeMasteryPct,
  selectSmartMode,
} from "@/lib/studyUtils"
import type { FlashcardSearchFilters } from "@/lib/studyUtils"

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
  // S188: section heading for source grounding display
  section_heading: string | null
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

// S184: Collection type for filter dropdown
interface CollectionItem {
  id: string
  name: string
}

// S184: Search response type
interface FlashcardSearchResponse {
  items: Flashcard[]
  total: number
  page: number
  page_size: number
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

async function fetchFlashcardSearch(filters: FlashcardSearchFilters): Promise<FlashcardSearchResponse> {
  const params = buildSearchParams(filters)
  const query = params.toString()
  const res = await fetch(`${API_BASE}/flashcards/search${query ? `?${query}` : ""}`)
  if (!res.ok) return { items: [], total: 0, page: 1, page_size: 20 }
  return res.json() as Promise<FlashcardSearchResponse>
}

async function fetchCollections(): Promise<CollectionItem[]> {
  const res = await fetch(`${API_BASE}/collections/tree`)
  if (!res.ok) return []
  const tree = await res.json() as { id: string; name: string }[]
  return tree.map((c) => ({ id: c.id, name: c.name }))
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
      {/* S188: Section heading label */}
      {card.section_heading && !editing && (
        <p className="text-xs text-muted-foreground">{card.section_heading}</p>
      )}
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
                    <Tooltip formatter={(value) => [value ?? 0, "Cards"]} />
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
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
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
// InsightsAccordion (S185) -- merged DeckHealthPanel + HealthReportPanel + StrugglingPanel
// Uses INSIGHTS_SECTIONS constant for section enumeration (load-bearing for tests).
// ---------------------------------------------------------------------------

interface InsightsAccordionProps {
  documentId: string
  cards: Flashcard[]
}

function InsightsAccordion({ documentId, cards }: InsightsAccordionProps) {
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
          Insights ({totalCards} card{totalCards !== 1 ? "s" : ""}, {masteredPct}% mastered)
        </span>
        {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {isOpen && (
        <div className="flex flex-col gap-4 pt-2">
          {/* Sections driven by INSIGHTS_SECTIONS constant */}
          {INSIGHTS_SECTIONS.includes("health_report") && (
            <HealthReportPanel documentId={documentId} />
          )}
          {INSIGHTS_SECTIONS.includes("bloom_audit") && (
            <DeckHealthPanel documentId={documentId} />
          )}
          {INSIGHTS_SECTIONS.includes("struggling") && (
            <StrugglingPanel documentId={documentId} />
          )}
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// GenerateButton (S185) -- single Generate Cards button with chevron disclosure
// Replaces GeneratePanel + SmartGeneratePanel. Uses buildSmartGenerateParams.
// ---------------------------------------------------------------------------

const COUNT_OPTIONS = [5, 10, 20, 50]
const DIFFICULTY_OPTIONS = [
  { value: "easy", label: "Easy" },
  { value: "medium", label: "Medium" },
  { value: "hard", label: "Hard" },
]

const SMART_MODE_LABEL: Record<string, string> = {
  basic: "basic cards",
  feynman: "Feynman-style questions",
  cloze: "cloze cards",
}

const GENERATE_MODE_OPTIONS = [
  { value: "basic", label: "Basic" },
  { value: "graph", label: "Graph (entities)" },
  { value: "cloze", label: "Cloze" },
  { value: "technical", label: "Technical" },
]

interface GenerateButtonProps {
  documentId: string
  sections: SectionItem[]
  cards: Flashcard[]
  onGenerate: (req: {
    scope: "full" | "section"
    section_heading: string | null
    count: number
    difficulty: "easy" | "medium" | "hard"
  }) => void
  onGenerateFromGraph: (k: number) => void
  onGenerateCloze: (sectionId: string, count: number) => void
  isGenerating: boolean
  isClozeGenerating: boolean
}

function GenerateButton({
  documentId,
  sections,
  cards,
  onGenerate,
  onGenerateFromGraph,
  onGenerateCloze,
  isGenerating,
  isClozeGenerating,
}: GenerateButtonProps) {
  const [optionsOpen, setOptionsOpen] = useState(false)
  const [scope, setScope] = useState<"full" | "section">("full")
  const [sectionHeading, setSectionHeading] = useState<string | null>(null)
  const [difficulty, setDifficulty] = useState<"easy" | "medium" | "hard">("medium")
  const [mode, setMode] = useState<"basic" | "graph" | "cloze" | "technical">("basic")
  const [count, setCount] = useState(10)
  const [clozeSectionId, setClozeSectionId] = useState<string | null>(null)

  const masteryPct = computeMasteryPct(cards)
  const isAnyGenerating = isGenerating || isClozeGenerating

  function handleSmartGenerate() {
    const params = buildSmartGenerateParams(masteryPct, documentId)
    if (params.smart_mode === "feynman") {
      onGenerateFromGraph(5)
    } else if (params.smart_mode === "cloze") {
      const firstSection = sections[0]
      if (firstSection) {
        onGenerateCloze(firstSection.id, 5)
      } else {
        onGenerate({ scope: "full", section_heading: null, count: 10, difficulty: "medium" })
      }
    } else {
      onGenerate({
        scope: params.scope,
        section_heading: params.section_heading,
        count: params.count,
        difficulty: params.difficulty,
      })
    }
  }

  function handleAdvancedGenerate() {
    if (mode === "graph" || mode === "technical") {
      onGenerateFromGraph(5)
    } else if (mode === "cloze") {
      if (clozeSectionId) {
        onGenerateCloze(clozeSectionId, count)
      }
    } else {
      onGenerate({ scope, section_heading: sectionHeading, count, difficulty })
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1">
        <button
          onClick={handleSmartGenerate}
          disabled={isAnyGenerating || !documentId}
          className="flex items-center gap-2 rounded-l bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {isAnyGenerating ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Zap size={14} />
          )}
          Generate Cards
        </button>
        <button
          onClick={() => setOptionsOpen((v) => !v)}
          disabled={!documentId}
          className="flex items-center rounded-r border-l border-primary-foreground/20 bg-primary px-2 py-2 text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          aria-label="Toggle generate options"
        >
          {optionsOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      </div>
      {!isAnyGenerating && (
        <span className="text-xs text-muted-foreground">
          Adaptive: {SMART_MODE_LABEL[selectSmartMode(masteryPct)] ?? "basic cards"}
        </span>
      )}
      {isAnyGenerating && (
        <span className="text-xs text-muted-foreground">
          Generating {SMART_MODE_LABEL[selectSmartMode(masteryPct)]}...
        </span>
      )}

      {/* Disclosure panel: advanced options */}
      {optionsOpen && (
        <div className="flex flex-col gap-3 rounded-md border border-border bg-muted/30 p-3 mt-1">
          <div className="flex flex-wrap items-end gap-3">
            {/* Mode */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground">Mode</label>
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value as typeof mode)}
                className="rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {GENERATE_MODE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>

            {/* Scope (only for basic mode) */}
            {mode === "basic" && (
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
            )}

            {/* Section picker for basic + section scope */}
            {mode === "basic" && scope === "section" && sections.length > 0 && (
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-muted-foreground">Section</label>
                <select
                  value={sectionHeading ?? ""}
                  onChange={(e) => setSectionHeading(e.target.value || null)}
                  className="max-w-[240px] rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="">Select section...</option>
                  {sections.map((s) => (
                    <option key={s.id} value={s.heading}>{s.heading}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Section picker for cloze mode (required) */}
            {mode === "cloze" && (
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
                    <option key={s.id} value={s.id}>{s.heading}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Difficulty (basic mode only) */}
            {mode === "basic" && (
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-muted-foreground">Difficulty</label>
                <select
                  value={difficulty}
                  onChange={(e) => setDifficulty(e.target.value as "easy" | "medium" | "hard")}
                  className="rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  {DIFFICULTY_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Count */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground">Count</label>
              <select
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
                className="rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {COUNT_OPTIONS.map((n) => (
                  <option key={n} value={n}>{n} cards</option>
                ))}
              </select>
            </div>

            <button
              onClick={handleAdvancedGenerate}
              disabled={
                isAnyGenerating ||
                (mode === "basic" && scope === "section" && !sectionHeading) ||
                (mode === "cloze" && !clozeSectionId)
              }
              className="flex items-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {isAnyGenerating && <Loader2 size={14} className="animate-spin" />}
              Generate
            </button>
          </div>
        </div>
      )}
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

  // S184: search state
  const [searchQuery, setSearchQuery] = useState("")
  const [debouncedQuery, setDebouncedQuery] = useState("")
  const [filterDocId, setFilterDocId] = useState<string | null>(null)
  const [filterCollectionId, setFilterCollectionId] = useState<string | null>(null)
  const [filterTag, setFilterTag] = useState<string | null>(null)
  const [filterFsrsState, setFilterFsrsState] = useState<string | null>(null)
  const [searchPage, setSearchPage] = useState(1)

  // S184: 300ms debounce for search query
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery), 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  // Reset page when any filter changes
  useEffect(() => {
    setSearchPage(1)
  }, [debouncedQuery, filterDocId, filterCollectionId, filterTag, filterBloomMin, filterBloomMax, filterFsrsState, filterType])

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

  // S184: Unified flashcard search query
  const searchFilters: FlashcardSearchFilters = {
    query: debouncedQuery || undefined,
    document_id: filterDocId ?? activeDocumentId ?? undefined,
    collection_id: filterCollectionId ?? undefined,
    tag: filterTag ?? undefined,
    bloom_level_min: filterBloomMin > 1 ? filterBloomMin : undefined,
    bloom_level_max: filterBloomMax < 6 ? filterBloomMax : undefined,
    fsrs_state: filterFsrsState ?? undefined,
    flashcard_type: filterType ?? undefined,
    page: searchPage,
    page_size: 20,
  }
  const { data: searchResult, isLoading: cardsLoading, isError: cardsError } = useQuery<FlashcardSearchResponse>({
    queryKey: ["flashcards-search", debouncedQuery, filterDocId, activeDocumentId, filterCollectionId, filterTag, filterBloomMin, filterBloomMax, filterFsrsState, filterType, searchPage],
    queryFn: () => fetchFlashcardSearch(searchFilters),
  })
  const cards = searchResult?.items ?? []
  const totalCards = searchResult?.total ?? 0

  // S184: Collections list for filter dropdown
  const { data: collectionList = [] } = useQuery<CollectionItem[]>({
    queryKey: ["collections-list"],
    queryFn: fetchCollections,
    staleTime: 60_000,
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
      void queryClient.invalidateQueries({ queryKey: ["flashcards-search"] })
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
      void queryClient.invalidateQueries({ queryKey: ["flashcards-search"] })
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
      void queryClient.invalidateQueries({ queryKey: ["flashcards-search"] })
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
      void queryClient.invalidateQueries({ queryKey: ["flashcards-search"] })
      toast.success("Flashcard updated")
    },
    onError: () => toast.error("Failed to update flashcard"),
  })

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteFlashcard(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["flashcards-search"] })
      toast.success("Flashcard deleted")
    },
    onError: () => toast.error("Failed to delete flashcard"),
  })

  // Delete all mutation
  const deleteAllMutation = useMutation({
    mutationFn: () => deleteAllFlashcards(activeDocumentId!),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["flashcards-search"] })
    },
    onError: () => toast.error("Failed to clear flashcards"),
  })

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
          void queryClient.invalidateQueries({ queryKey: ["flashcards-search"] })
          if (activeDocumentId) {
            void queryClient.invalidateQueries({ queryKey: ["section-heatmap", activeDocumentId] })
          }
        }}
      />
    )
  }

  return (
    <div className="flex h-full flex-col gap-6 overflow-auto p-6">
      {/* S185: Top CTA row -- Start Studying + Generate Cards (max 2 CTAs above the fold) */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => setStudying(true)}
          disabled={cards.length === 0}
          className="flex items-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          <PlayCircle size={14} />
          Start Studying
        </button>
        {activeDocumentId && (
          <GenerateButton
            documentId={activeDocumentId}
            sections={sections}
            cards={cards}
            onGenerate={(req) => { setGenerateErrorKind(null); generateMutation.mutate(req) }}
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
          />
        )}
      </div>

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

      {/* S184: Search bar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <input
            type="text"
            placeholder="Search flashcards..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-md border border-border bg-background pl-3 pr-8 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X size={14} />
            </button>
          )}
        </div>
        {/* Document filter dropdown */}
        <select
          value={filterDocId ?? activeDocumentId ?? ""}
          onChange={(e) => {
            const v = e.target.value || null
            setFilterDocId(v)
            setActiveDocument(v)
          }}
          className="rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring max-w-xs"
        >
          <option value="">All documents</option>
          {docList.map((doc) => (
            <option key={doc.id} value={doc.id}>{doc.title}</option>
          ))}
        </select>
      </div>

      {/* S184: Active filter chips */}
      {(filterDocId || filterCollectionId || filterTag || filterFsrsState || filterType || filterBloomMin > 1 || filterBloomMax < 6) && (
        <div className="flex flex-wrap gap-2">
          {filterDocId && (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
              Doc: {docList.find((d) => d.id === filterDocId)?.title ?? filterDocId}
              <button onClick={() => { setFilterDocId(null); setActiveDocument(null) }} className="hover:text-primary/70"><X size={12} /></button>
            </span>
          )}
          {filterFsrsState && (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
              State: {FSRS_STATE_LABELS[filterFsrsState] ?? filterFsrsState}
              <button onClick={() => setFilterFsrsState(null)} className="hover:text-primary/70"><X size={12} /></button>
            </span>
          )}
          {filterType && (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
              Type: {filterType}
              <button onClick={() => setFilterType(null)} className="hover:text-primary/70"><X size={12} /></button>
            </span>
          )}
          {filterTag && (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
              Tag: {filterTag}
              <button onClick={() => setFilterTag(null)} className="hover:text-primary/70"><X size={12} /></button>
            </span>
          )}
          {filterCollectionId && (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
              Collection: {collectionList.find((c) => c.id === filterCollectionId)?.name ?? filterCollectionId}
              <button onClick={() => setFilterCollectionId(null)} className="hover:text-primary/70"><X size={12} /></button>
            </span>
          )}
          {(filterBloomMin > 1 || filterBloomMax < 6) && (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
              Bloom: {BLOOM_LEVEL_LABELS[filterBloomMin] ?? filterBloomMin} - {BLOOM_LEVEL_LABELS[filterBloomMax] ?? filterBloomMax}
              <button onClick={() => { setFilterBloomMin(1); setFilterBloomMax(6) }} className="hover:text-primary/70"><X size={12} /></button>
            </span>
          )}
          <button
            onClick={() => {
              setFilterDocId(null); setActiveDocument(null)
              setFilterCollectionId(null); setFilterTag(null)
              setFilterFsrsState(null); setFilterType(null)
              setFilterBloomMin(1); setFilterBloomMax(6)
              setSearchQuery("")
            }}
            className="text-xs text-muted-foreground hover:text-foreground underline"
          >
            Clear all
          </button>
        </div>
      )}

      {/* S184: Quick filter row */}
      <div className="flex flex-wrap gap-2">
        <select
          value={filterCollectionId ?? ""}
          onChange={(e) => setFilterCollectionId(e.target.value || null)}
          className="rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
        >
          <option value="">Any collection</option>
          {collectionList.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <input
          type="text"
          placeholder="Filter by tag..."
          value={filterTag ?? ""}
          onChange={(e) => setFilterTag(e.target.value || null)}
          className="rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground w-32"
        />
        <select
          value={filterFsrsState ?? ""}
          onChange={(e) => setFilterFsrsState(e.target.value || null)}
          className="rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
        >
          <option value="">Any state</option>
          {Object.entries(FSRS_STATE_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <select
          value={filterType ?? ""}
          onChange={(e) => setFilterType(e.target.value || null)}
          className="rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
        >
          <option value="">Any type</option>
          <option value="definition">Definition</option>
          <option value="concept">Concept</option>
          <option value="application">Application</option>
          <option value="analysis">Analysis</option>
          <option value="evaluation">Evaluation</option>
          <option value="cloze">Cloze</option>
          <option value="trace">Trace</option>
          <option value="concept_explanation">Concept explanation</option>
        </select>
        <select
          value={filterBloomMin}
          onChange={(e) => setFilterBloomMin(Number(e.target.value))}
          className="rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
        >
          {Object.entries(BLOOM_LEVEL_LABELS).map(([k, v]) => (
            <option key={k} value={k}>Min: {v}</option>
          ))}
        </select>
        <select
          value={filterBloomMax}
          onChange={(e) => setFilterBloomMax(Number(e.target.value))}
          className="rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
        >
          {Object.entries(BLOOM_LEVEL_LABELS).map(([k, v]) => (
            <option key={k} value={k}>Max: {v}</option>
          ))}
        </select>
      </div>

      {/* Sub-tab toggle (only when a document is active) */}
      {activeDocumentId && (
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
      )}

      {activeDocumentId && studySubTab === "history" ? (
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

          {/* S184: Card grid -- always visible (search is global) */}
          <section className="flex flex-col gap-4">
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
                      {debouncedQuery
                        ? `No flashcards found for "${debouncedQuery}". Try a different search term.`
                        : "No flashcards match your filters."}
                      {!debouncedQuery && activeDocumentId && " Try generating cards with Smart Generate above."}
                      {!debouncedQuery && !activeDocumentId && " Select a document or adjust your search to find cards."}
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
                      {totalCards} card{totalCards !== 1 ? "s" : ""} total
                      {totalCards > 20 && ` (page ${searchPage} of ${Math.ceil(totalCards / 20)})`}
                    </span>
                    {totalCards > 20 && (
                      <div className="flex gap-1">
                        <button
                          disabled={searchPage <= 1}
                          onClick={() => setSearchPage((p) => Math.max(1, p - 1))}
                          className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40"
                        >
                          Prev
                        </button>
                        <button
                          disabled={searchPage >= Math.ceil(totalCards / 20)}
                          onClick={() => setSearchPage((p) => p + 1)}
                          className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40"
                        >
                          Next
                        </button>
                      </div>
                    )}
                    <div className="ml-auto flex gap-2">
                      {activeDocumentId && (
                        <button
                          onClick={handleExportCsv}
                          className="flex items-center gap-2 rounded border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
                        >
                          <Download size={14} />
                          Export CSV
                        </button>
                      )}
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

          {/* Document-specific panels (only when a document is active) */}
          {activeDocumentId && (
            <>
              {/* Deck Status accordion (S178/S185 merged) */}
              <InsightsAccordion documentId={activeDocumentId} cards={cards} />

              {/* Weak Areas panel */}
              <WeakAreasPanel
                documentId={activeDocumentId}
                onSelectSection={(_heading) => {
                  window.scrollTo({ top: 0, behavior: "smooth" })
                }}
              />

              {/* Progress dashboard (S23b) */}
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
