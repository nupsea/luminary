/**
 * ProgressDashboard — progress stats panel for the Study tab.
 *
 * Sections:
 *   1. Summary stats row (4 Cards: mastered, retention, streak, study time)
 *   2. Retention curve (Recharts LineChart, 0-30 days, ReferenceLine at 80%)
 *   3. Mastery heatmap (per-section stability grid with tooltip)
 *   4. Streak calendar (90-day grid, GitHub-style contribution squares)
 *
 * Data sources:
 *   GET /study/stats/{documentId}
 *   GET /study/history?days=90&document_id={documentId}
 */

import { useEffect, useState } from "react"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ReferenceLine,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts"
import { Loader2 } from "lucide-react"

const API_BASE = "http://localhost:8000"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CardStabilityItem {
  card_id: string
  stability: number
  due_date: string | null
}

interface SectionStabilityItem {
  section_heading: string | null
  avg_stability: number
  card_count: number
}

interface StudyStats {
  total_cards: number
  cards_mastered: number
  avg_retention: number
  current_streak: number
  total_study_time_minutes: number
  per_section_stability: SectionStabilityItem[]
  all_card_stabilities: CardStabilityItem[]
}

interface HistoryItem {
  date: string
  cards_reviewed: number
  study_time_minutes: number
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function fetchStats(documentId: string): Promise<StudyStats | null> {
  const res = await fetch(`${API_BASE}/study/stats/${documentId}`)
  if (!res.ok) return null
  return res.json() as Promise<StudyStats>
}

async function fetchHistory(documentId: string): Promise<HistoryItem[]> {
  const res = await fetch(
    `${API_BASE}/study/history?document_id=${documentId}&days=90`,
  )
  if (!res.ok) return []
  return res.json() as Promise<HistoryItem[]>
}

// ---------------------------------------------------------------------------
// Retention curve helpers
// ---------------------------------------------------------------------------

function buildRetentionCurveData(
  cardStabilities: CardStabilityItem[],
): { day: number; recall: number }[] {
  if (cardStabilities.length === 0) return []
  return Array.from({ length: 31 }, (_, day) => {
    const recalls = cardStabilities.map((c) =>
      c.stability > 0 ? Math.exp(-day / c.stability) * 100 : 0,
    )
    const avg = recalls.reduce((a, b) => a + b, 0) / recalls.length
    return { day, recall: Math.round(avg * 10) / 10 }
  })
}

// ---------------------------------------------------------------------------
// Color helpers
// ---------------------------------------------------------------------------

function stabilityColor(avg: number): string {
  if (avg < 1) return "bg-red-200"
  if (avg < 2) return "bg-red-100"
  if (avg < 4) return "bg-amber-100"
  if (avg < 7) return "bg-yellow-100"
  return "bg-green-100"
}

function streakCellColor(cards: number): string {
  if (cards === 0) return "bg-secondary"
  if (cards <= 5) return "bg-green-200"
  if (cards <= 15) return "bg-green-400"
  return "bg-green-600"
}

// ---------------------------------------------------------------------------
// SummaryCard
// ---------------------------------------------------------------------------

function SummaryCard({
  label,
  value,
}: {
  label: string
  value: string | number
}) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-card p-4">
      <span className="text-2xl font-bold text-foreground">{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ProgressDashboard
// ---------------------------------------------------------------------------

interface ProgressDashboardProps {
  documentId: string
}

export function ProgressDashboard({ documentId }: ProgressDashboardProps) {
  const [stats, setStats] = useState<StudyStats | null>(null)
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [hoveredSection, setHoveredSection] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    async function load() {
      const [s, h] = await Promise.all([
        fetchStats(documentId),
        fetchHistory(documentId),
      ])
      if (cancelled) return
      setStats(s)
      setHistory(h)
      setLoading(false)
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [documentId])

  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <Loader2 size={24} className="animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!stats) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Could not load progress data.
      </p>
    )
  }

  // --- Retention curve ---
  const curveData = buildRetentionCurveData(stats.all_card_stabilities)

  // --- Streak calendar (90 days) ---
  const historyMap = new Map<string, number>()
  for (const item of history) {
    historyMap.set(item.date, item.cards_reviewed)
  }

  // Build 91 day array starting from 90 days ago
  const calendarDays: { dateStr: string; cards: number }[] = []
  const today = new Date()
  for (let i = 90; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(d.getDate() - i)
    const dateStr = d.toISOString().slice(0, 10)
    calendarDays.push({ dateStr, cards: historyMap.get(dateStr) ?? 0 })
  }

  // Pad to align to week boundaries (Sunday = 0)
  const firstDayOfWeek = new Date(calendarDays[0]?.dateStr ?? today).getDay()
  const paddedDays: ({ dateStr: string; cards: number } | null)[] = [
    ...Array(firstDayOfWeek).fill(null),
    ...calendarDays,
  ]
  // Chunk into weeks
  const weeks: (({ dateStr: string; cards: number } | null)[])[] = []
  for (let i = 0; i < paddedDays.length; i += 7) {
    weeks.push(paddedDays.slice(i, i + 7))
  }

  const retentionPct = Math.round(stats.avg_retention * 100)
  const studyHours = (stats.total_study_time_minutes / 60).toFixed(1)

  return (
    <div className="flex flex-col gap-6">
      {/* 1. Summary stats row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <SummaryCard label="Cards Mastered" value={stats.cards_mastered} />
        <SummaryCard label="Avg Retention" value={`${retentionPct}%`} />
        <SummaryCard label="Current Streak" value={`${stats.current_streak}d`} />
        <SummaryCard label="Study Time" value={`${studyHours}h`} />
      </div>

      {/* 2. Retention curve */}
      {curveData.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            Predicted Retention Curve (next 30 days)
          </h3>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={curveData}
                margin={{ top: 4, right: 8, bottom: 4, left: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis
                  dataKey="day"
                  tickFormatter={(v: number) => `${v}d`}
                  tick={{ fontSize: 11 }}
                />
                <YAxis
                  domain={[0, 100]}
                  tickFormatter={(v: number) => `${v}%`}
                  tick={{ fontSize: 11 }}
                  width={36}
                />
                <RechartsTooltip
                  formatter={(value: string | number | undefined) => [
                    value !== undefined ? `${value}%` : "",
                    "Recall",
                  ]}
                  labelFormatter={(label: unknown) => `Day ${label as number}`}
                />
                <ReferenceLine
                  y={80}
                  stroke="#f59e0b"
                  strokeDasharray="4 2"
                  label={{ value: "Target 80%", position: "right", fontSize: 10 }}
                />
                <Line
                  type="monotone"
                  dataKey="recall"
                  stroke="hsl(var(--primary))"
                  dot={false}
                  strokeWidth={2}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* 3. Mastery heatmap */}
      {stats.per_section_stability.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            Section Mastery Heatmap
          </h3>
          <div className="flex flex-wrap gap-2">
            {stats.per_section_stability.map((sec, i) => {
              const label = sec.section_heading ?? "Unsectioned"
              const isHovered = hoveredSection === label
              return (
                <div
                  key={i}
                  className={`relative cursor-default rounded px-3 py-2 text-xs font-medium transition-all ${stabilityColor(sec.avg_stability)}`}
                  onMouseEnter={() => setHoveredSection(label)}
                  onMouseLeave={() => setHoveredSection(null)}
                >
                  <span className="line-clamp-1 max-w-[14rem]">{label}</span>
                  {isHovered && (
                    <div className="absolute bottom-full left-1/2 z-10 mb-1 -translate-x-1/2 rounded bg-popover px-2 py-1 text-xs text-popover-foreground shadow-md whitespace-nowrap">
                      {label} — stability {sec.avg_stability.toFixed(2)} ({sec.card_count} cards)
                    </div>
                  )}
                </div>
              )
            })}
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="h-3 w-3 rounded-sm bg-red-200" />
            <span>Low</span>
            <span className="h-3 w-3 rounded-sm bg-amber-100" />
            <span>Medium</span>
            <span className="h-3 w-3 rounded-sm bg-green-100" />
            <span>High</span>
          </div>
        </div>
      )}

      {/* 4. Streak calendar */}
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold text-foreground">
          90-Day Study Activity
        </h3>
        <div className="flex gap-1">
          {weeks.map((week, wi) => (
            <div key={wi} className="flex flex-col gap-1">
              {week.map((day, di) =>
                day === null ? (
                  <div key={di} className="h-3 w-3" />
                ) : (
                  <div
                    key={di}
                    title={`${day.dateStr}: ${day.cards} cards`}
                    className={`h-3 w-3 rounded-sm ${streakCellColor(day.cards)}`}
                  />
                ),
              )}
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="h-3 w-3 rounded-sm bg-secondary border border-border" />
          <span>No sessions</span>
          <span className="h-3 w-3 rounded-sm bg-green-200" />
          <span>1-5</span>
          <span className="h-3 w-3 rounded-sm bg-green-400" />
          <span>6-15</span>
          <span className="h-3 w-3 rounded-sm bg-green-600" />
          <span>16+</span>
        </div>
      </div>
    </div>
  )
}
