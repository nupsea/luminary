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
import { useEffect, useState } from "react"
import {
  AlertCircle,
  BookOpen,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  CornerDownRight,
  Layers,
  Loader2,
  MessageSquare,
  Pencil,

  Plus,
  StickyNote,
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
import { AnimatePresence, motion } from "framer-motion"
import { toast } from "sonner"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { useAppStore } from "@/store"
import {
  FLASHCARD_CARD_LIMIT,
  StudySession,
} from "@/components/StudySession"
import {
  TEACHBACK_CARD_LIMIT,
  TeachbackSession,
} from "@/components/TeachbackSession"
import { SessionManager } from "@/components/SessionManager"
import { CollectionStudyDashboard } from "@/components/study/CollectionStudyDashboard"
import { SessionHistory } from "@/components/study/SessionHistory"
import {
  type PrepareStudySessionOptions,
  type PreparedStudySessionOutcome,
  type StudyMode,
  prepareStudySession,
} from "@/lib/studySessionService"


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

// StudySessionItem, SessionListResponse, SessionCardDetail moved to @/lib/studyApi.ts

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

// fetchSessions, fetchSessionCards, TeachbackResultItem, fetchSessionTeachbackResults,
// deleteStudySession moved to @/lib/studyApi.ts and @/components/SessionManager.tsx

async function fetchStudyStats(documentId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/study/stats/${documentId}`)
  if (!res.ok) throw new Error("Failed to load study stats")
  return res.json()
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

async function generateTechnicalFlashcards(req: {
  document_id: string
  scope: "full" | "section"
  section_heading: string | null
  count: number
}): Promise<Flashcard[]> {
  const res = await fetch(`${API_BASE}/flashcards/generate-technical`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new GenerateError(res.status, "Failed to generate technical flashcards")
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

async function bulkDeleteFlashcards(ids: string[]): Promise<{ deleted: number }> {
  const res = await fetch(`${API_BASE}/flashcards/bulk-delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  })
  if (!res.ok) throw new Error("Failed to delete selected flashcards")
  return res.json() as Promise<{ deleted: number }>
}

async function deleteAllFlashcardsForDocument(documentId: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/flashcards/document/${encodeURIComponent(documentId)}`,
    { method: "DELETE" },
  )
  if (!res.ok) throw new Error("Failed to delete all flashcards")
}

async function generateFlashcardsFromGraph(
  documentId: string,
  k: number,
): Promise<Flashcard[]> {
  const res = await fetch(`${API_BASE}/flashcards/generate-from-graph`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId, k }),
  })
  if (!res.ok) throw new GenerateError(res.status, "Failed to generate graph flashcards")
  return res.json() as Promise<Flashcard[]>
}

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
  selectionMode?: boolean
  selected?: boolean
  onToggleSelect?: (id: string) => void
}

function FlashcardCard({
  card,
  onUpdate,
  onDelete,
  isUpdating,
  isDeleting,
  selectionMode = false,
  selected = false,
  onToggleSelect,
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
    <Card
      className={`flex flex-col gap-3 ${selected ? "ring-2 ring-primary" : ""}`}
    >
      {selectionMode && (
        <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelect?.(card.id)}
            className="h-4 w-4 rounded border-border text-primary focus:ring-primary"
          />
          Select for bulk delete
        </label>
      )}
      {/* S188: Section heading label */}
      {card.section_heading && !editing && (
        <p className="text-xs text-muted-foreground">{card.section_heading}</p>
      )}
      {/* Flip container */}
      <div className="relative w-full mt-2 min-h-[140px]" style={{ perspective: "1000px" }}>
        <AnimatePresence mode="wait">
          {/* Front (Question only) */}
          {!editing && !showAnswer && (
            <motion.div
              key="front"
            initial={{ rotateX: -180, opacity: 0 }}
            animate={{ rotateX: 0, opacity: 1 }}
            exit={{ rotateX: 180, opacity: 0 }}
            transition={{ duration: 0.4, ease: "easeInOut" }}
            style={{ backfaceVisibility: "hidden" }}
            className="w-full flex flex-col gap-2"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="flex-1 text-sm font-medium text-foreground">{card.question}</p>
              {!confirmDelete && (
                <div className="flex shrink-0 gap-1">
                  <button
                    onClick={(e) => { e.stopPropagation(); setEditing(true) }}
                    className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                    title="Edit"
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); setConfirmDelete(true) }}
                    className="rounded p-1 text-muted-foreground hover:bg-red-50 hover:text-red-600"
                    title="Delete"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              )}
            </div>
            <div>
              <button
                onClick={() => setShowAnswer(true)}
                className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 mt-1"
              >
                <ChevronDown size={12} /> Make it flip
              </button>
            </div>
          </motion.div>
        )}

        {/* Back (Question + Answer) */}
        {!editing && showAnswer && (
          <motion.div
            key="back"
            initial={{ rotateX: 180, opacity: 0 }}
            animate={{ rotateX: 0, opacity: 1 }}
            exit={{ rotateX: -180, opacity: 0 }}
            transition={{ duration: 0.4, ease: "easeInOut" }}
            style={{ backfaceVisibility: "hidden" }}
            className="w-full flex flex-col gap-2 rounded-lg border border-primary/20 bg-primary/5 p-3"
          >
            <p className="text-sm font-medium text-muted-foreground">{card.question}</p>
            <hr className="border-primary/10" />
            <MarkdownRenderer className="text-sm text-foreground">{card.answer}</MarkdownRenderer>
            <button
              onClick={() => setShowAnswer(false)}
              className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 mt-2 self-start"
            >
              <ChevronUp size={12} /> Hide answer
            </button>
          </motion.div>
        )}
        </AnimatePresence>

        {/* Editing mode */}
        {editing && (
          <div className="flex flex-col gap-3">
            <textarea
              value={editQuestion}
              onChange={(e) => setEditQuestion(e.target.value)}
              className="resize-none rounded border border-border bg-background p-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              rows={2}
              placeholder="Question..."
            />
            <textarea
              value={editAnswer}
              onChange={(e) => setEditAnswer(e.target.value)}
              className="resize-none rounded border border-border bg-background p-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              rows={3}
              placeholder="Answer..."
            />
          </div>
        )}
      </div>
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
  onGenerateTechnical: (req: {
    scope: "full" | "section"
    section_heading: string | null
    count: number
  }) => void
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
  onGenerateTechnical,
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
    if (mode === "technical") {
      onGenerateTechnical({ scope, section_heading: sectionHeading, count })
    } else if (mode === "graph") {
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

// SessionHistoryTab replaced by SessionManager component

// ---------------------------------------------------------------------------
// DocPicker
// ---------------------------------------------------------------------------

function DocPicker({ 
  docs, 
  activeId, 
  onSelect 
}: { 
  docs: DocListItem[], 
  activeId: string | null, 
  onSelect: (id: string | null) => void 
}) {
  return (
    <div className="flex items-center gap-2">
      <BookOpen size={16} className="text-muted-foreground" />
      <select
        value={activeId || ""}
        onChange={(e) => onSelect(e.target.value || null)}
        className="h-9 min-w-[200px] rounded-full border border-border bg-card px-4 py-1.5 text-xs font-bold uppercase tracking-wider text-foreground transition-all hover:border-primary/50 focus:border-primary focus:outline-none"
      >
        <option value="">- SELECT STANDALONE DOC -</option>
        {docs.map((d) => (
          <option key={d.id} value={d.id}>{d.title.toUpperCase()}</option>
        ))}
      </select>
    </div>
  )
}

// ---------------------------------------------------------------------------
// FlashcardManager (Standalone view for document-centric study)
// ---------------------------------------------------------------------------

function FlashcardManager({
  documentId,
  onStartStudy,
  onStartTeachback,
}: {
  documentId: string;
  onStartStudy: (filters?: any) => void;
  onStartTeachback: (filters?: any, resumeId?: string) => void;
}) {
  const [page, setPage] = useState(1)
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmBulkDelete, setConfirmBulkDelete] = useState<null | "selected" | "all">(null)
  const qc = useQueryClient()
  const { data: docList = [] } = useQuery<DocListItem[]>({
    queryKey: ["study-doc-list"],
    queryFn: fetchDocList,
  })

  const { data: stats } = useQuery({
    queryKey: ["study-stats", documentId],
    queryFn: () => fetchStudyStats(documentId),
    enabled: !!documentId,
  })

  const { data: searchResult, isLoading: cardsLoading } = useQuery<FlashcardSearchResponse>({
    queryKey: ["flashcards-search", documentId, page],
    queryFn: () => fetchFlashcardSearch({ document_id: documentId, page, page_size: 20 }),
  })

  const { data: docData } = useQuery<DocumentSections>({
    queryKey: ["document-sections", documentId],
    queryFn: () => fetchDocumentSections(documentId),
    enabled: !!documentId,
  })

  const cards = searchResult?.items ?? []
  const totalCards = searchResult?.total ?? 0
  const totalPages = Math.ceil(totalCards / 20)

  // Reset selection when document changes (avoids deleting wrong doc's cards)
  useEffect(() => {
    setSelectedIds(new Set())
    setSelectionMode(false)
  }, [documentId])

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function selectAllOnPage() {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      for (const c of cards) next.add(c.id)
      return next
    })
  }

  function clearSelection() {
    setSelectedIds(new Set())
  }

  // Mutations for update, delete, generate
  const updateMutation = useMutation({
    mutationFn: (args: { id: string; data: any }) => updateFlashcard(args.id, args.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["flashcards-search"] }),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteFlashcard,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["flashcards-search"] }),
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: bulkDeleteFlashcards,
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      qc.invalidateQueries({ queryKey: ["study-stats", documentId] })
      clearSelection()
      setSelectionMode(false)
      setConfirmBulkDelete(null)
      toast.success(`Deleted ${res.deleted} flashcard${res.deleted === 1 ? "" : "s"}`)
    },
    onError: () => toast.error("Failed to delete selected flashcards"),
  })

  const deleteAllMutation = useMutation({
    mutationFn: () => deleteAllFlashcardsForDocument(documentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      qc.invalidateQueries({ queryKey: ["study-stats", documentId] })
      clearSelection()
      setSelectionMode(false)
      setConfirmBulkDelete(null)
      toast.success("All flashcards deleted for this document")
    },
    onError: () => toast.error("Failed to delete flashcards"),
  })

  const generateMutation = useMutation({
    mutationFn: generateFlashcards,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      toast.success("Cards generated successfully")
    },
    onError: (err: Error) => {
      const msg = err instanceof GenerateError && err.status === 503
        ? "Ollama is unavailable. Start it with: ollama serve"
        : "Failed to generate cards"
      toast.error(msg)
    },
  })

  const generateTechnicalMutation = useMutation({
    mutationFn: generateTechnicalFlashcards,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      toast.success("Technical cards generated successfully")
    },
    onError: (err: Error) => {
      const msg = err instanceof GenerateError && err.status === 503
        ? "Ollama is unavailable. Start it with: ollama serve"
        : "Failed to generate technical cards"
      toast.error(msg)
    },
  })

  const generateGraphMutation = useMutation({
    mutationFn: ({ documentId: did, k }: { documentId: string; k: number }) =>
      generateFlashcardsFromGraph(did, k),
    onSuccess: (cards) => {
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      toast.success(
        cards.length > 0
          ? `Generated ${cards.length} graph card${cards.length === 1 ? "" : "s"}`
          : "No graph relationships found for this document",
      )
    },
    onError: (err: Error) => {
      const msg = err instanceof GenerateError && err.status === 503
        ? "Ollama is unavailable. Start it with: ollama serve"
        : "Failed to generate graph flashcards"
      toast.error(msg)
    },
  })

  const generateClozeMutation = useMutation({
    mutationFn: ({ sectionId, count }: { sectionId: string; count: number }) =>
      generateClozeFlashcards(sectionId, count),
    onSuccess: (cards) => {
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      toast.success(`Generated ${cards.length} cloze card${cards.length === 1 ? "" : "s"}`)
    },
    onError: (err: Error) => {
      const msg = err instanceof GenerateError && err.status === 503
        ? "Ollama is unavailable. Start it with: ollama serve"
        : "Failed to generate cloze flashcards"
      toast.error(msg)
    },
  })

  // Hero card subtitle: branch on (due, new, zero, no cards)
  function heroSubtitle(): string {
    if (!stats) return ""
    const due = stats.due_today ?? 0
    const newCount = stats.new_today ?? 0
    if (due > 0 && newCount > 0) {
      return `${due} due for review and ${newCount} new card${newCount === 1 ? "" : "s"} to learn today.`
    }
    if (due > 0) {
      return `You have ${due} flashcard${due === 1 ? "" : "s"} due for review today.`
    }
    if (newCount > 0) {
      return `${newCount} new card${newCount === 1 ? "" : "s"} ready to learn.`
    }
    if (totalCards > 0) {
      return "You're all caught up. Practice early or generate more cards."
    }
    return "No flashcards yet. Generate some to begin."
  }

  const dueOrNew = (stats?.due_today ?? 0) > 0 || (stats?.new_today ?? 0) > 0
  const showHero = !!stats || totalCards > 0
  const heroAccent = dueOrNew
    ? "from-primary/20 to-secondary/10"
    : totalCards > 0
      ? "from-emerald-500/15 to-emerald-500/5"
      : "from-muted to-muted/40"

  return (
    <div className="flex flex-col gap-8">
      {/* Ready to Study hero — always visible when we have stats or cards */}
      {showHero && (
         <Card className={`relative overflow-hidden border-none bg-gradient-to-br ${heroAccent} p-8 shadow-2xl transition-all`}>
            <div className="flex flex-col gap-6">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-2xl font-bold text-foreground">
                    {dueOrNew ? "Ready to Study" : totalCards > 0 ? "All Caught Up" : "No Cards Yet"}
                  </h2>
                  <p className="text-muted-foreground">{heroSubtitle()}</p>
                </div>
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/20 text-primary">
                  <Zap size={24} />
                </div>
              </div>

              {stats && (
                <div className="flex gap-4">
                  <div className="rounded-xl bg-background/50 px-4 py-2 border border-border/50">
                    <p className="text-xs text-muted-foreground uppercase">New</p>
                    <p className="text-lg font-bold text-foreground">{stats.new_today ?? 0}</p>
                  </div>
                  <div className="rounded-xl bg-background/50 px-4 py-2 border border-border/50">
                    <p className="text-xs text-muted-foreground uppercase">Review</p>
                    <p className="text-lg font-bold text-foreground">{stats.due_today ?? 0}</p>
                  </div>
                  <div className="flex-1 rounded-xl bg-background/50 px-4 py-2 border border-border/50">
                    <div className="flex justify-between mb-1">
                      <p className="text-xs text-muted-foreground uppercase">Mastery</p>
                      <p className="text-xs font-bold text-foreground">{stats.mastery_pct ?? 0}%</p>
                    </div>
                    <Progress value={stats.mastery_pct ?? 0} className="h-1.5" />
                  </div>
                </div>
              )}

              {totalCards > 0 && (
                <div className="flex gap-3">
                  <button
                    onClick={() => onStartStudy({ document_id: documentId })}
                    disabled={!dueOrNew}
                    className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-blue-600 py-4 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition-all hover:bg-blue-700 hover:shadow-xl active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 disabled:shadow-none"
                  >
                    <Zap size={18} />
                    {dueOrNew ? "Flashcard Review" : "Nothing Due"}
                  </button>
                  <button
                    onClick={() => onStartTeachback({ document_id: documentId })}
                    className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-violet-600 py-4 text-sm font-semibold text-white shadow-lg shadow-violet-600/20 transition-all hover:bg-violet-700 hover:shadow-xl active:scale-[0.98]"
                  >
                    <MessageSquare size={18} />
                    Teach-back Session
                  </button>
                </div>
              )}
            </div>
            {/* Subtle glow effect */}
            <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-primary/10 blur-[100px]" />
         </Card>
      )}

      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="flex flex-col gap-1">
          <h2 className="text-2xl font-bold tracking-tight text-foreground">
            {docList.find(d => d.id === documentId)?.title || "Source Grounding"}
          </h2>
          <p className="text-sm text-muted-foreground">Managing {totalCards} flashcards for this document</p>
        </div>

        <GenerateButton
          documentId={documentId}
          sections={docData?.sections || []}
          cards={cards}
          onGenerate={(req) => generateMutation.mutate({ ...req, document_id: documentId })}
          onGenerateFromGraph={(k) => generateGraphMutation.mutate({ documentId, k })}
          onGenerateCloze={(sectionId, count) =>
            generateClozeMutation.mutate({ sectionId, count })
          }
          onGenerateTechnical={(req) =>
            generateTechnicalMutation.mutate({ ...req, document_id: documentId })
          }
          isGenerating={
            generateMutation.isPending ||
            generateTechnicalMutation.isPending ||
            generateGraphMutation.isPending
          }
          isClozeGenerating={generateClozeMutation.isPending}
        />
      </div>

      {/* Bulk selection toolbar */}
      {totalCards > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-muted/30 px-4 py-2 text-sm">
          {!selectionMode ? (
            <button
              onClick={() => setSelectionMode(true)}
              className="rounded border border-border bg-background px-3 py-1 text-xs font-medium text-foreground hover:bg-accent"
            >
              Select cards
            </button>
          ) : (
            <>
              <span className="text-xs font-medium text-muted-foreground">
                {selectedIds.size} selected
              </span>
              <button
                onClick={selectAllOnPage}
                className="rounded border border-border bg-background px-3 py-1 text-xs font-medium text-foreground hover:bg-accent"
              >
                Select all on page
              </button>
              <button
                onClick={clearSelection}
                className="rounded border border-border bg-background px-3 py-1 text-xs font-medium text-foreground hover:bg-accent"
              >
                Clear
              </button>
              <button
                onClick={() => setConfirmBulkDelete("selected")}
                disabled={selectedIds.size === 0 || bulkDeleteMutation.isPending}
                className="rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                Delete selected ({selectedIds.size})
              </button>
              <button
                onClick={() => {
                  setSelectionMode(false)
                  clearSelection()
                }}
                className="ml-auto rounded border border-border bg-background px-3 py-1 text-xs font-medium text-foreground hover:bg-accent"
              >
                Done
              </button>
            </>
          )}
          <button
            onClick={() => setConfirmBulkDelete("all")}
            disabled={deleteAllMutation.isPending}
            className="ml-auto rounded border border-red-300 bg-red-50 px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100 disabled:opacity-50 dark:border-red-900 dark:bg-red-950/30 dark:text-red-400"
          >
            Delete all ({totalCards})
          </button>
        </div>
      )}

      {/* Bulk delete confirmation */}
      {confirmBulkDelete && (
        <div className="flex items-center gap-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200">
          <AlertCircle size={16} />
          <span className="flex-1">
            {confirmBulkDelete === "selected"
              ? `Permanently delete ${selectedIds.size} selected flashcard${selectedIds.size === 1 ? "" : "s"}? This cannot be undone.`
              : `Permanently delete ALL ${totalCards} flashcards for this document? This cannot be undone.`}
          </span>
          <button
            onClick={() => {
              if (confirmBulkDelete === "selected") {
                bulkDeleteMutation.mutate(Array.from(selectedIds))
              } else {
                deleteAllMutation.mutate()
              }
            }}
            disabled={bulkDeleteMutation.isPending || deleteAllMutation.isPending}
            className="flex items-center gap-1 rounded bg-red-600 px-3 py-1 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50"
          >
            {(bulkDeleteMutation.isPending || deleteAllMutation.isPending) && (
              <Loader2 size={12} className="animate-spin" />
            )}
            Confirm delete
          </button>
          <button
            onClick={() => setConfirmBulkDelete(null)}
            className="rounded border border-red-300 px-3 py-1 text-xs font-medium hover:bg-red-100 dark:hover:bg-red-900/40"
          >
            Cancel
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 flex flex-col gap-4">
          {cardsLoading ? (
            <div className="flex py-10 justify-center"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>
          ) : cards.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border py-20 bg-card/10">
              <Zap size={32} className="text-muted-foreground opacity-30" />
              <p className="text-muted-foreground italic">No cards found. Generate some to get started.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {cards.map(c => (
                <FlashcardCard
                  key={c.id}
                  card={c}
                  onUpdate={(id, data) => updateMutation.mutate({ id, data })}
                  onDelete={(id) => deleteMutation.mutate(id)}
                  isUpdating={updateMutation.isPending}
                  isDeleting={deleteMutation.isPending}
                  selectionMode={selectionMode}
                  selected={selectedIds.has(c.id)}
                  onToggleSelect={toggleSelect}
                />
              ))}
            </div>
          )}
          
          {totalPages > 1 && (
            <div className="flex justify-center gap-2 mt-4">
              <button onClick={() => setPage(p => Math.max(1, p-1))} className="text-xs uppercase font-bold text-primary px-3 py-1 bg-secondary rounded-full hover:bg-secondary/80">Prev</button>
              <span className="text-xs font-bold flex items-center">{page} / {totalPages}</span>
              <button onClick={() => setPage(p => Math.min(totalPages, p+1))} className="text-xs uppercase font-bold text-primary px-3 py-1 bg-secondary rounded-full hover:bg-secondary/80">Next</button>
            </div>
          )}
        </div>
        
        <div className="flex flex-col gap-6">
          <InsightsAccordion documentId={documentId} cards={cards} />
          <WeakAreasPanel documentId={documentId} onSelectSection={() => {}} />
        </div>
      </div>

      {/* Session history scoped to this document */}
      <SessionHistory
        scope={{ kind: "document", id: documentId }}
        onResumeTeachback={(sid) =>
          onStartTeachback({ document_id: documentId }, sid)
        }
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Study page
// ---------------------------------------------------------------------------

export default function Study() {
  const navigate = useNavigate()
  const {
    activeDocumentId,
    setActiveDocument,
    activeCollectionId,
    setActiveCollectionId,
  } = useAppStore()

  // Study-session lifecycle lives entirely in this one state variable.
  // It is ONLY mutated by explicit user handlers (handleStartFlashcard,
  // handleStartTeachback, handleExit). Session creation happens in the
  // "preparing" phase via prepareStudySession (one user click = one call).
  type StudyPhase =
    | { phase: "idle" }
    | { phase: "preparing"; mode: StudyMode }
    | {
        phase: "ready"
        mode: StudyMode
        outcome: PreparedStudySessionOutcome
        scopeForBeginNew: PrepareStudySessionOptions
      }
  const [studyPhase, setStudyPhase] = useState<StudyPhase>({ phase: "idle" })

  const { data: collections = [], isLoading: loadingCollections } = useQuery({
    queryKey: ["collections-list"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/collections/tree`)
      if (!res.ok) return []
      return res.json() as Promise<any[]>
    },
  })

  const { data: docList = [] } = useQuery<DocListItem[]>({
    queryKey: ["study-doc-list"],
    queryFn: fetchDocList,
  })

  type StudyFiltersLike = {
    tag?: string
    document_ids?: string[]
    note_ids?: string[]
  }
  const startStudy = async (
    mode: StudyMode,
    filters: StudyFiltersLike | null,
    resumeId: string | null,
  ) => {
    // Guard: if we are already preparing or in a ready state, ignore the
    // click. This prevents a double-click (or a re-fired event from a
    // downstream component) from launching two prepareStudySession calls.
    if (studyPhase.phase !== "idle") return

    setStudyPhase({ phase: "preparing", mode })
    const options: PrepareStudySessionOptions = {
      mode,
      documentId: activeDocumentId ?? null,
      collectionId: activeCollectionId ?? null,
      filters: filters ?? undefined,
      cardLimit:
        mode === "teachback" ? TEACHBACK_CARD_LIMIT : FLASHCARD_CARD_LIMIT,
      resumeSessionId: resumeId,
    }
    try {
      const outcome = await prepareStudySession(options)
      setStudyPhase({
        phase: "ready",
        mode,
        outcome,
        scopeForBeginNew: { ...options, resumeSessionId: null },
      })
    } catch (err) {
      console.warn("Failed to prepare study session", err)
      setStudyPhase({ phase: "idle" })
      toast.error("Could not start study session. Please try again.")
    }
  }

  const handleStartFlashcard = (filters?: StudyFiltersLike) => {
    void startStudy("flashcard", filters ?? null, null)
  }

  const handleStartTeachback = (
    filters?: StudyFiltersLike,
    resumeId?: string,
  ) => {
    void startStudy("teachback", filters ?? null, resumeId ?? null)
  }

  // Walk the nested collection tree to find a name by id.
  const findCollectionName = (
    items: any[],
    id: string | null,
  ): string | null => {
    if (!id) return null
    for (const item of items) {
      if (item.id === id) return item.name ?? null
      if (item.children?.length) {
        const found = findCollectionName(item.children, id)
        if (found) return found
      }
    }
    return null
  }

  const activeDocTitle =
    docList.find((d) => d.id === activeDocumentId)?.title ?? null
  const activeCollectionName = findCollectionName(collections, activeCollectionId)
  const subjectLabel =
    activeCollectionName || activeDocTitle || null

  const handleExit = () => {
    setStudyPhase({ phase: "idle" })
  }

  // ---- Active session routes ------------------------------------------------
  if (studyPhase.phase === "preparing") {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2
          size={32}
          className={
            studyPhase.mode === "teachback"
              ? "animate-spin text-violet-500"
              : "animate-spin text-primary"
          }
        />
      </div>
    )
  }

  if (studyPhase.phase === "ready" && studyPhase.mode === "flashcard") {
    return (
      <StudySession
        initial={
          studyPhase.outcome.kind === "empty"
            ? { kind: "empty" }
            : {
                kind: studyPhase.outcome.kind,
                session: studyPhase.outcome.session,
              }
        }
        scopeForBeginNew={studyPhase.scopeForBeginNew}
        onExit={handleExit}
      />
    )
  }

  if (studyPhase.phase === "ready" && studyPhase.mode === "teachback") {
    return (
      <TeachbackSession
        initial={
          studyPhase.outcome.kind === "empty"
            ? { kind: "empty" }
            : {
                kind: studyPhase.outcome.kind,
                session: studyPhase.outcome.session,
              }
        }
        scopeForBeginNew={studyPhase.scopeForBeginNew}
        onExit={handleExit}
        subjectLabel={subjectLabel}
      />
    )
  }

  // ---- Main study dashboard -------------------------------------------------
  return (
    <div className="flex h-full flex-col bg-background">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border bg-card/30 px-8 py-3 backdrop-blur-md">
        <div className="flex items-center gap-8">
          <h1
            className="cursor-pointer text-xl font-bold tracking-tight text-foreground"
            onClick={() => {
              setActiveCollectionId(null)
              setActiveDocument(null)
            }}
          >
            Study
          </h1>

          <DocPicker
            docs={docList}
            activeId={activeDocumentId}
            onSelect={(id) => {
              setActiveDocument(id)
              if (id) setActiveCollectionId(null)
            }}
          />
        </div>
      </div>

      <div className="flex-1 overflow-auto p-8 lg:p-12">
        {activeCollectionId ? (
          <CollectionStudyDashboard
            collectionId={activeCollectionId}
            onBack={() => setActiveCollectionId(null)}
            onStartStudy={handleStartFlashcard}
            onStartTeachback={(filters, resumeId) =>
              handleStartTeachback(filters, resumeId)
            }
            onNavigateToCollection={(id) => setActiveCollectionId(id)}
          />
        ) : activeDocumentId ? (
          <FlashcardManager
            documentId={activeDocumentId}
            onStartStudy={handleStartFlashcard}
            onStartTeachback={(f) => handleStartTeachback(f)}
          />
        ) : (
          /* Landing page: session manager + collection grid */
          <div className="flex flex-col gap-10">
            <SessionManager
              onContinueTeachback={(sessionId, documentId, collectionId) => {
                if (documentId) setActiveDocument(documentId)
                if (collectionId) setActiveCollectionId(collectionId)
                
                const filters: any = {}
                if (documentId) filters.document_id = documentId
                if (collectionId) filters.collection_id = collectionId
                
                handleStartTeachback(
                  Object.keys(filters).length > 0 ? filters : null,
                  sessionId
                )
              }}
            />

            {/* Focused Enclaves heading */}
            <div className="flex flex-col gap-2 max-w-2xl">
              <motion.h1
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="text-3xl font-bold tracking-tight text-foreground"
              >
                Focused Enclaves
              </motion.h1>
              <p className="text-muted-foreground text-lg">
                Grouped knowledge silos for topic-centric learning.
              </p>
            </div>

            {loadingCollections ? (
              <div className="flex py-20 justify-center">
                <Loader2 className="h-10 w-10 animate-spin text-primary" />
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                {(() => {
                  const flatten = (items: any[], parentName: string | null = null): any[] => {
                    let result: any[] = []
                    items.forEach((item) => {
                      result.push({ ...item, _parentName: parentName, _isNested: parentName !== null })
                      if (item.children && item.children.length > 0) {
                        result = result.concat(flatten(item.children, item.name))
                      }
                    })
                    return result
                  }
                  const flatCollections = flatten(collections)
                  return flatCollections.map((coll, idx) => (
                    <motion.div
                      key={coll.id}
                      initial={{ opacity: 0, y: 15 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: idx * 0.05 }}
                      whileHover={{ y: -5 }}
                      onClick={() => {
                        setActiveCollectionId(coll.id)
                        setActiveDocument(null)
                      }}
                      className={`group relative cursor-pointer overflow-hidden rounded-3xl border p-6 shadow-sm transition-all hover:border-primary/40 hover:bg-card hover:shadow-xl ${
                        coll._isNested ? "border-primary/20 bg-card/30" : "border-border bg-card/40"
                      }`}
                    >
                      {coll._isNested && (
                        <div className="absolute top-3 right-3 flex items-center gap-1 text-[10px] text-muted-foreground/60">
                          <CornerDownRight size={10} />
                          <span className="font-medium">{coll._parentName}</span>
                        </div>
                      )}
                      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary transition-all group-hover:bg-primary group-hover:text-primary-foreground group-hover:scale-110">
                        <Layers size={24} />
                      </div>
                      <div className="mt-6 flex flex-col gap-2">
                        <h3 className="text-lg font-semibold text-foreground">{coll.name}</h3>
                        <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed opacity-70">
                          {coll.description || "Synthesize knowledge across documents and notes."}
                        </p>
                      </div>
                      <div className="mt-4 flex items-center gap-3">
                        {coll.document_count > 0 || coll.note_count > 0 ? (
                          <>
                            {coll.document_count > 0 && (
                              <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                                <BookOpen size={12} className="text-blue-500/70" />
                                {coll.document_count} {coll.document_count === 1 ? "doc" : "docs"}
                              </span>
                            )}
                            {coll.note_count > 0 && (
                              <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                                <StickyNote size={12} className="text-amber-500/70" />
                                {coll.note_count} {coll.note_count === 1 ? "note" : "notes"}
                              </span>
                            )}
                            {coll.children && coll.children.length > 0 && (
                              <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                                <Layers size={12} className="text-primary/50" />
                                {coll.children.length} sub
                              </span>
                            )}
                          </>
                        ) : (
                          <span className="text-[11px] text-muted-foreground/50 italic">No sources yet</span>
                        )}
                      </div>
                      <div className="mt-4 flex items-center justify-between border-t border-border/50 pt-4">
                        <div className="text-xs font-semibold uppercase text-primary opacity-0 transition-opacity group-hover:opacity-100">
                          Enter Context
                        </div>
                        <ChevronRight size={16} className="text-primary translate-x-4 opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100" />
                      </div>
                    </motion.div>
                  ))
                })()}

                <motion.button
                  onClick={() => navigate("/notes")}
                  className="flex flex-col items-center justify-center gap-4 rounded-3xl border-2 border-dashed border-border/60 bg-transparent p-6 transition-all hover:bg-accent/30 hover:border-primary/40 group text-muted-foreground"
                >
                  <Plus size={24} className="group-hover:scale-110 transition-transform" />
                  <div className="text-center">
                    <p className="text-sm font-semibold uppercase">New Enclave</p>
                  </div>
                </motion.button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

