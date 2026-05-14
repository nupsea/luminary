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
import { AlertCircle, BookOpen, StickyNote, Target, TrendingUp, Sparkles, Loader2, Brain } from "lucide-react"
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
import { StudyHabitsSection } from "@/components/StudyHabitsSection"
import { logger } from "@/lib/logger"
import { apiGet, apiPost } from "@/lib/apiClient"
import { GoalsList } from "@/components/goals/GoalsList"
import type { DocListItem } from "./Study"
import type { components } from "@/types/api"

// ---------------------------------------------------------------------------
// Types -- API shapes sourced from generated `src/types/api.ts` (audit #15).
// ---------------------------------------------------------------------------

type DailyHistoryItem = components["schemas"]["DailyHistoryItem"]
type DueCountResponse = components["schemas"]["DueCountResponse"]
type SessionListResponse = components["schemas"]["SessionListResponse"]

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

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

const fetchStudyHistory = (days: number): Promise<DailyHistoryItem[]> =>
  apiGet<DailyHistoryItem[]>("/study/history", {
    days,
    tz_offset_minutes: new Date().getTimezoneOffset(),
  })

const fetchDueCount = (): Promise<DueCountResponse> =>
  apiGet<DueCountResponse>("/study/due-count")

const fetchOverview = (): Promise<MonitoringOverview> =>
  apiGet<MonitoringOverview>("/monitoring/overview")

async function fetchDocList(): Promise<DocListItem[]> {
  try {
    const data = await apiGet<{ items: DocListItem[] }>("/documents", {
      sort: "newest",
      page: 1,
      page_size: 100,
    })
    return data.items ?? []
  } catch {
    return []
  }
}

const fetchRecentNotes = (): Promise<NoteListResponse> =>
  apiGet<NoteListResponse>("/notes", { page: 1, page_size: 100 })

const fetchSessions = (): Promise<SessionListResponse> =>
  apiGet<SessionListResponse>("/study/sessions", { page: 1, page_size: 50 })

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
  accent = "primary",
}: {
  label: string
  value: string | number
  icon: React.ComponentType<{ size?: number; className?: string }>
  loading: boolean
  accent?: "primary" | "emerald" | "amber" | "rose"
}) {
  const accentClasses: Record<string, { ring: string; iconBg: string; iconText: string }> = {
    primary: { ring: "ring-primary/10", iconBg: "bg-primary/10", iconText: "text-primary" },
    emerald: { ring: "ring-emerald-500/10", iconBg: "bg-emerald-500/10", iconText: "text-emerald-600" },
    amber: { ring: "ring-amber-500/10", iconBg: "bg-amber-500/10", iconText: "text-amber-600" },
    rose: { ring: "ring-rose-500/10", iconBg: "bg-rose-500/10", iconText: "text-rose-600" },
  }
  const a = accentClasses[accent] ?? accentClasses.primary

  // Animated counter for numeric values
  const [displayValue, setDisplayValue] = useState<string | number>(0)
  useEffect(() => {
    if (loading) return
    if (typeof value === "number") {
      const duration = 600
      const start = performance.now()
      const end = value
      function tick(now: number) {
        const elapsed = now - start
        const progress = Math.min(elapsed / duration, 1)
        // Ease-out cubic
        const eased = 1 - Math.pow(1 - progress, 3)
        setDisplayValue(Math.round(eased * end))
        if (progress < 1) requestAnimationFrame(tick)
      }
      requestAnimationFrame(tick)
    } else {
      setDisplayValue(value)
    }
  }, [value, loading])

  return (
    <div className={`flex flex-col gap-3 rounded-2xl border border-border/50 bg-card/60 backdrop-blur-xl px-5 py-4 shadow-lg ring-1 ${a.ring} transition-all duration-200 hover:shadow-xl hover:-translate-y-0.5`}>
      <div className="flex items-center gap-3">
        <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${a.iconBg}`}>
          <Icon size={18} className={a.iconText} />
        </div>
        <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{label}</span>
      </div>
      {loading ? (
        <Skeleton className="h-8 w-20" />
      ) : (
        <span className="text-3xl font-extrabold tracking-tight text-foreground">{displayValue}</span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// KnowledgeGapScanner (Added in Phase 4)
// ---------------------------------------------------------------------------

function KnowledgeGapScanner({ docs }: { docs: DocListItem[] }) {
  const [selectedDoc, setSelectedDoc] = useState<string>("")
  const [selectedSec, setSelectedSec] = useState<string>("")
  const [sections, setSections] = useState<{id: string, heading: string}[]>([])
  const [analyzing, setAnalyzing] = useState(false)
  const [gaps, setGaps] = useState<string[] | null>(null)

  useEffect(() => {
    if (!selectedDoc) {
      setSections([])
      return
    }
    apiGet<{ sections?: { id: string; heading: string }[] }>(
      `/documents/${selectedDoc}`,
    )
      .then(d => {
        setSections(d.sections || [])
        if (d.sections && d.sections.length > 0) {
          setSelectedSec(d.sections[0].id)
        }
      })
      .catch(() => setSections([]))
  }, [selectedDoc])

  const handleScan = async () => {
    if (!selectedDoc || !selectedSec) return
    setAnalyzing(true)
    setGaps(null)
    try {
      const data = await apiPost<{ gaps: string[] }>("/notes/gap-detect", {
        document_id: selectedDoc,
        section_id: selectedSec,
      })
      setGaps(data.gaps)
    } catch {
      setGaps([])
    } finally {
      setAnalyzing(false)
    }
  }

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <h2 className="text-lg font-semibold text-foreground">Knowledge Gap Scanner</h2>
        <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary border border-primary/20 shadow-sm">AI</span>
      </div>
      <div className="flex flex-col gap-5 rounded-2xl border border-border/50 bg-card/60 backdrop-blur-xl p-6 shadow-xl relative overflow-hidden group">
        <div className="absolute inset-0 bg-gradient-to-br from-primary/5 via-transparent to-transparent opacity-50" />
        <div className="relative z-10 flex flex-col gap-4">
          <p className="text-sm text-muted-foreground">Select a document section you've taken notes on. The AI will compare your notes against the original text to identify missing concepts.</p>
          
          <div className="flex flex-col sm:flex-row gap-3 items-end">
            <div className="flex flex-col gap-1.5 flex-1">
              <label className="text-xs font-medium text-muted-foreground">Document</label>
              <select
                value={selectedDoc}
                onChange={(e) => setSelectedDoc(e.target.value)}
                className="rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 transition-shadow"
              >
                <option value="">Select a document</option>
                {docs.map(d => <option key={d.id} value={d.id}>{d.title}</option>)}
              </select>
            </div>
            
            {selectedDoc && sections.length > 0 && (
              <div className="flex flex-col gap-1.5 flex-1">
                <label className="text-xs font-medium text-muted-foreground">Section</label>
                <select
                  value={selectedSec}
                  onChange={(e) => setSelectedSec(e.target.value)}
                  className="rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 transition-shadow"
                >
                  <option value="">Select section</option>
                  {sections.map(s => <option key={s.id} value={s.id}>{s.heading || `Section ${s.id}`}</option>)}
                </select>
              </div>
            )}

            <button
              onClick={handleScan}
              disabled={!selectedDoc || !selectedSec || analyzing}
              className="flex h-[38px] items-center justify-center gap-2 rounded-xl bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-all shadow-md hover:shadow-lg hover:-translate-y-0.5 mt-2 sm:mt-0"
            >
              {analyzing ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
              Analyze Notes
            </button>
          </div>

          {/* Results */}
          {gaps && (
            <div className="mt-2 flex flex-col gap-3 rounded-xl bg-background/80 p-5 border border-border/80 shadow-inner animate-in slide-in-from-top-2 duration-300">
              <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
                <Brain size={16} className="text-primary"/> 
                Identified Learning Gaps
              </h3>
              {gaps.length === 0 ? (
                <p className="text-sm text-emerald-600 dark:text-emerald-400 font-medium">Excellent! Your notes cover all key concepts from this section perfectly.</p>
              ) : (
                <ul className="flex flex-col gap-2.5">
                  {gaps.map((gap, i) => (
                    <li key={i} className="flex gap-2.5 text-sm text-foreground items-start bg-muted/30 p-3 rounded-lg border border-border/40">
                      <span className="text-primary font-bold mt-0.5">•</span>
                      <span className="leading-relaxed">{gap}</span>
                    </li>
                  ))}
                </ul>
              )}
              {gaps.length > 0 && (
                <p className="text-xs text-muted-foreground mt-2 italic flex gap-1 items-center">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary/60" />
                  Tip: Use the context menus in the reading view to generate flashcards based on these gaps.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
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
        <div className="rounded-2xl bg-gradient-to-r from-primary/10 via-primary/5 to-transparent px-6 py-4 border border-primary/10">
          <h2 className="text-lg font-bold text-foreground">Overview</h2>
          <p className="text-xs text-muted-foreground mt-0.5">Your learning journey at a glance</p>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard
            label="Mastery Score"
            value={masteryScore !== null ? `${masteryScore}%` : "—"}
            icon={TrendingUp}
            loading={masteryLoading}
            accent="primary"
          />
          <StatCard
            label="Cards Mastered"
            value={cardsMastered}
            icon={BookOpen}
            loading={masteryLoading}
            accent="emerald"
          />
          <StatCard
            label="Due Today"
            value={dueCount}
            icon={Target}
            loading={dueLoading}
            accent="rose"
          />
          <StatCard
            label="Study Streak"
            value={streak}
            icon={TrendingUp}
            loading={historyLoading}
            accent="amber"
          />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <StatCard
            label="Reviews (30d)"
            value={totalReviewed}
            icon={BookOpen}
            loading={historyLoading}
            accent="primary"
          />
          <StatCard
            label="Documents"
            value={overview?.total_documents ?? 0}
            icon={BookOpen}
            loading={overviewLoading}
            accent="emerald"
          />
          <StatCard
            label="Notes"
            value={notes.length}
            icon={StickyNote}
            loading={notesLoading}
            accent="amber"
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

      {/* Study Habits: streaks, XP, achievements (Phase 7) */}
      <StudyHabitsSection />

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

      {/* Knowledge Gap Scanner (Added in Phase 4) */}
      {!docsLoading && docList.length > 0 && (
         <KnowledgeGapScanner docs={docList} />
      )}

      {/* Learning Goals -- now shared with Study tab; replaced legacy GoalsPanel in S211 */}
      <GoalsList />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

/**
 * Format a Date as a local-time YYYY-MM-DD key (not UTC). Matches the
 * backend's `/study/history` bucketing when called with tz_offset_minutes.
 */
function localDateKey(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

function computeStreak(history: DailyHistoryItem[]): number {
  if (history.length === 0) return 0
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  let streak = 0
  const cursor = new Date(today)
  const histSet = new Set(history.filter((h) => h.cards_reviewed > 0).map((h) => h.date))
  while (true) {
    if (!histSet.has(localDateKey(cursor))) break
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
    const key = localDateKey(d)
    result.push({ date: key.slice(5), cards_reviewed: map.get(key) ?? 0 })
  }
  return result
}
