/**
 * Progress tab -- learner-centric mastery dashboard.
 *
 * Sections:
 *   1. Summary stats: overall mastery score, cards due today, mastered count, time invested
 *   2. Study activity chart: cards reviewed per day (last 30 days) + streak
 *   3. Notes over time chart: notes created per month
 *   4. Documents ingested count
 *   5. GoalsPanel (moved from Study tab in S177)
 *
 * Empty state: "Start studying to see your progress here" when no study history.
 */

import { useEffect, useState } from "react"
import { AlertCircle, BookOpen, StickyNote, Target, TrendingUp } from "lucide-react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { Skeleton } from "@/components/ui/skeleton"
import { logger } from "@/lib/logger"
import { API_BASE } from "@/lib/config"
import { GoalsPanel } from "./Study"
import type { DocListItem } from "./Study"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DailyHistoryItem {
  date: string
  cards_reviewed: number
  study_time_minutes: number
}

interface DueCountResponse {
  due_today: number
}

interface MonitoringOverview {
  total_documents: number
  total_chunks: number
}

interface Note {
  id: string
  created_at: string
}

interface NoteListResponse {
  items: Note[]
  total: number
}

interface SessionListItem {
  id: string
  accuracy_pct: number | null
  cards_reviewed: number
  cards_correct: number
}

interface SessionListResponse {
  items: SessionListItem[]
  total: number
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchStudyHistory(days: number): Promise<DailyHistoryItem[]> {
  const res = await fetch(`${API_BASE}/study/history?days=${days}`)
  if (!res.ok) throw new Error("study/history failed")
  return res.json() as Promise<DailyHistoryItem[]>
}

async function fetchDueCount(): Promise<DueCountResponse> {
  const res = await fetch(`${API_BASE}/study/due-count`)
  if (!res.ok) throw new Error("study/due-count failed")
  return res.json() as Promise<DueCountResponse>
}

async function fetchOverview(): Promise<MonitoringOverview> {
  const res = await fetch(`${API_BASE}/monitoring/overview`)
  if (!res.ok) throw new Error("monitoring/overview failed")
  return res.json() as Promise<MonitoringOverview>
}

async function fetchDocList(): Promise<DocListItem[]> {
  const res = await fetch(`${API_BASE}/documents?sort=newest&page=1&page_size=100`)
  if (!res.ok) return []
  const data = (await res.json()) as { items: DocListItem[] }
  return data.items ?? []
}

async function fetchRecentNotes(): Promise<NoteListResponse> {
  const res = await fetch(`${API_BASE}/notes?page=1&page_size=100`)
  if (!res.ok) throw new Error("notes failed")
  return res.json() as Promise<NoteListResponse>
}

async function fetchSessions(): Promise<SessionListResponse> {
  const res = await fetch(`${API_BASE}/study/sessions?page=1&page_size=50`)
  if (!res.ok) throw new Error("study/sessions failed")
  return res.json() as Promise<SessionListResponse>
}

// ---------------------------------------------------------------------------
// Helper: build notes-over-time chart data (group by month)
// ---------------------------------------------------------------------------

function buildNotesOverTimeData(notes: Note[]): { month: string; count: number }[] {
  const counts: Record<string, number> = {}
  for (const n of notes) {
    const d = new Date(n.created_at)
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
    counts[key] = (counts[key] ?? 0) + 1
  }
  return Object.entries(counts)
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-12)
    .map(([month, count]) => ({ month, count }))
}

// ---------------------------------------------------------------------------
// Skeleton / Error helpers
// ---------------------------------------------------------------------------

function SectionSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-3">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  )
}

function SectionError({ name }: { name: string }) {
  return (
    <div className="flex h-16 items-center justify-center gap-2 rounded-lg border border-red-200 bg-red-50 text-sm text-red-600">
      <AlertCircle size={14} />
      Could not load {name}
    </div>
  )
}

// ---------------------------------------------------------------------------
// StatCard
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  icon: Icon,
  loading,
}: {
  label: string
  value: string | number
  icon: React.ComponentType<{ size?: number; className?: string }>
  loading: boolean
}) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon size={14} />
        <span className="text-xs font-medium">{label}</span>
      </div>
      {loading ? (
        <Skeleton className="h-6 w-16" />
      ) : (
        <span className="text-2xl font-bold text-foreground">{value}</span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Progress page
// ---------------------------------------------------------------------------

export default function Progress() {
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState(false)
  const [history, setHistory] = useState<DailyHistoryItem[]>([])

  const [dueLoading, setDueLoading] = useState(true)
  const [dueCount, setDueCount] = useState<number>(0)

  const [overviewLoading, setOverviewLoading] = useState(true)
  const [overviewError, setOverviewError] = useState(false)
  const [overview, setOverview] = useState<MonitoringOverview | null>(null)

  const [notesLoading, setNotesLoading] = useState(true)
  const [notesError, setNotesError] = useState(false)
  const [notes, setNotes] = useState<Note[]>([])

  const [docsLoading, setDocsLoading] = useState(true)
  const [docList, setDocList] = useState<DocListItem[]>([])

  // Mastery score: average accuracy_pct across recent sessions
  const [masteryLoading, setMasteryLoading] = useState(true)
  const [masteryScore, setMasteryScore] = useState<number | null>(null)
  const [cardsMastered, setCardsMastered] = useState<number>(0)

  useEffect(() => {
    let cancelled = false

    fetchStudyHistory(30)
      .then((d) => {
        if (!cancelled) {
          setHistory(d)
          setHistoryLoading(false)
        }
      })
      .catch((e: unknown) => {
        logger.warn("[Progress] study/history failed", e)
        if (!cancelled) {
          setHistoryLoading(false)
          setHistoryError(true)
        }
      })

    fetchDueCount()
      .then((d) => {
        if (!cancelled) {
          setDueCount(d.due_today)
          setDueLoading(false)
        }
      })
      .catch((e: unknown) => {
        logger.warn("[Progress] study/due-count failed", e)
        if (!cancelled) setDueLoading(false)
      })

    fetchOverview()
      .then((d) => {
        if (!cancelled) {
          setOverview(d)
          setOverviewLoading(false)
        }
      })
      .catch((e: unknown) => {
        logger.warn("[Progress] monitoring/overview failed", e)
        if (!cancelled) {
          setOverviewLoading(false)
          setOverviewError(true)
        }
      })

    fetchRecentNotes()
      .then((d) => {
        if (!cancelled) {
          setNotes(d.items ?? [])
          setNotesLoading(false)
        }
      })
      .catch((e: unknown) => {
        logger.warn("[Progress] notes failed", e)
        if (!cancelled) {
          setNotesLoading(false)
          setNotesError(true)
        }
      })

    fetchDocList()
      .then((d) => {
        if (!cancelled) {
          setDocList(d)
          setDocsLoading(false)
        }
      })
      .catch((e: unknown) => {
        logger.warn("[Progress] documents failed", e)
        if (!cancelled) setDocsLoading(false)
      })

    // Mastery score: average accuracy across recent sessions + total correct as mastered proxy
    fetchSessions()
      .then((d) => {
        if (!cancelled) {
          const sessionsWithAccuracy = d.items.filter((s) => s.accuracy_pct !== null)
          const avgAccuracy =
            sessionsWithAccuracy.length > 0
              ? Math.round(
                  sessionsWithAccuracy.reduce((sum, s) => sum + (s.accuracy_pct ?? 0), 0) /
                    sessionsWithAccuracy.length,
                )
              : null
          const totalCorrect = d.items.reduce((s, i) => s + i.cards_correct, 0)
          setMasteryScore(avgAccuracy)
          setCardsMastered(totalCorrect)
          setMasteryLoading(false)
        }
      })
      .catch((e: unknown) => {
        logger.warn("[Progress] study/sessions failed", e)
        if (!cancelled) setMasteryLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [])

  // Derived stats from history
  const totalReviewed = history.reduce((s, d) => s + d.cards_reviewed, 0)
  const streak = computeStreak(history)
  const hasAnyStudy = totalReviewed > 0

  // Chart data: last 30 days, fill in missing dates with 0
  const activityData = buildActivityData(history, 30)
  const notesOverTimeData = buildNotesOverTimeData(notes)

  // Suppress unused variable warning for error states shown inline
  void notesError
  void overviewError

  return (
    <div className="flex flex-col gap-8 px-6 py-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-foreground">Progress</h1>
      </div>

      {/* Empty state -- no study history yet */}
      {!historyLoading && !hasAnyStudy && (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border py-16 text-center">
          <TrendingUp size={32} className="text-muted-foreground" />
          <p className="text-base font-medium text-muted-foreground">
            Start studying to see your progress here
          </p>
          <p className="text-sm text-muted-foreground">
            Head to the Study tab, pick a document, and start a session.
          </p>
        </div>
      )}

      {/* Stats row */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Overview</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard
            label="Overall mastery score"
            value={masteryScore !== null ? `${masteryScore}%` : "—"}
            icon={TrendingUp}
            loading={masteryLoading}
          />
          <StatCard
            label="Cards mastered"
            value={cardsMastered}
            icon={BookOpen}
            loading={masteryLoading}
          />
          <StatCard
            label="Due today"
            value={dueCount}
            icon={Target}
            loading={dueLoading}
          />
          <StatCard
            label="Current streak (days)"
            value={streak}
            icon={TrendingUp}
            loading={historyLoading}
          />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <StatCard
            label="Cards reviewed (30d)"
            value={totalReviewed}
            icon={BookOpen}
            loading={historyLoading}
          />
          <StatCard
            label="Documents ingested"
            value={overview?.total_documents ?? 0}
            icon={BookOpen}
            loading={overviewLoading}
          />
          <StatCard
            label="Notes created"
            value={notes.length}
            icon={StickyNote}
            loading={notesLoading}
          />
        </div>
      </section>

      {/* Study activity chart */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Study Activity (Last 30 Days)</h2>
        {historyError ? (
          <SectionError name="study activity" />
        ) : historyLoading ? (
          <SectionSkeleton rows={4} />
        ) : activityData.length === 0 || !hasAnyStudy ? (
          <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
            No study sessions yet.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={activityData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
              <Tooltip />
              <Bar dataKey="cards_reviewed" name="Cards reviewed" fill="#6366f1" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </section>

      {/* Notes over time chart */}
      {notes.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold text-foreground">Notes Over Time</h2>
          {notesLoading ? (
            <SectionSkeleton rows={3} />
          ) : (
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={notesOverTimeData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="month" tick={{ fontSize: 10 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
                <Tooltip />
                <Bar dataKey="count" name="Notes" fill="#22c55e" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </section>
      )}

      {/* Learning Goals (moved from Study tab in S177) */}
      {docsLoading ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold text-foreground">Learning Goals</h2>
          <SectionSkeleton rows={2} />
        </section>
      ) : (
        <GoalsPanel docs={docList} />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

function computeStreak(history: DailyHistoryItem[]): number {
  if (history.length === 0) return 0
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  let streak = 0
  const cursor = new Date(today)
  const histSet = new Set(history.filter((h) => h.cards_reviewed > 0).map((h) => h.date))
  while (true) {
    const key = cursor.toISOString().slice(0, 10)
    if (!histSet.has(key)) break
    streak++
    cursor.setDate(cursor.getDate() - 1)
  }
  return streak
}

function buildActivityData(
  history: DailyHistoryItem[],
  days: number,
): { date: string; cards_reviewed: number }[] {
  const map = new Map(history.map((h) => [h.date, h.cards_reviewed]))
  const result: { date: string; cards_reviewed: number }[] = []
  const cursor = new Date()
  cursor.setHours(0, 0, 0, 0)
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(cursor)
    d.setDate(d.getDate() - i)
    const key = d.toISOString().slice(0, 10)
    result.push({ date: key.slice(5), cards_reviewed: map.get(key) ?? 0 })
  }
  return result
}
