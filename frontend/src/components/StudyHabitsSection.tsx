import { useQuery } from "@tanstack/react-query"
import { Flame, Trophy, Zap, Timer } from "lucide-react"
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
import { apiGet } from "@/lib/apiClient"
import { cn } from "@/lib/utils"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface XPHistoryItem {
  date: string
  xp: number
}

interface XPSummary {
  total_xp: number
  level: number
  xp_to_next_level: number
  today_xp: number
}

interface StreakData {
  current_streak: number
  longest_streak: number
  studied_today: boolean
  freezes_available: number
}

interface Achievement {
  key: string
  title: string
  description: string
  icon_name: string
  category: string
  progress_current: number
  progress_target: number
  unlocked_at: string | null
}

interface FocusStats {
  total_sessions: number
  completed_sessions: number
  completion_rate: number
  total_focus_minutes: number
  avg_duration_minutes: number
  days: number
}

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

async function fetchXPHistory(): Promise<XPHistoryItem[]> {
  try {
    return await apiGet<XPHistoryItem[]>("/engagement/xp/history", { days: 30 })
  } catch {
    return []
  }
}

const fetchXPSummary = (): Promise<XPSummary> =>
  apiGet<XPSummary>("/engagement/xp")

const fetchStreak = (): Promise<StreakData> =>
  apiGet<StreakData>("/engagement/streak")

async function fetchAchievements(): Promise<Achievement[]> {
  try {
    return await apiGet<Achievement[]>("/engagement/achievements")
  } catch {
    return []
  }
}

const fetchFocusStats = (): Promise<FocusStats> =>
  apiGet<FocusStats>("/engagement/focus/stats", { days: 7 })

// ---------------------------------------------------------------------------
// Icon map for achievements
// ---------------------------------------------------------------------------

const ICON_MAP: Record<string, typeof Trophy> = {
  flame: Flame,
  zap: Zap,
  trophy: Trophy,
  timer: Timer,
  "sticky-note": Trophy,
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StudyHabitsSection() {
  const { data: xpHistory, isLoading: historyLoading } = useQuery({
    queryKey: ["engagement-xp-history"],
    queryFn: fetchXPHistory,
    staleTime: 60_000,
  })

  const { data: xp } = useQuery({
    queryKey: ["engagement-xp"],
    queryFn: fetchXPSummary,
    staleTime: 60_000,
  })

  const { data: streak } = useQuery({
    queryKey: ["engagement-streak"],
    queryFn: fetchStreak,
    staleTime: 60_000,
  })

  const { data: achievements, isLoading: achievementsLoading } = useQuery({
    queryKey: ["engagement-achievements"],
    queryFn: fetchAchievements,
    staleTime: 120_000,
  })

  const { data: focusStats } = useQuery({
    queryKey: ["engagement-focus-stats"],
    queryFn: fetchFocusStats,
    staleTime: 60_000,
  })

  // Chart data: trim date to MM-DD for display
  const chartData = (xpHistory ?? []).map((d) => ({
    date: d.date.slice(5),
    xp: d.xp,
  }))

  const unlockedCount = achievements?.filter((a) => a.unlocked_at).length ?? 0
  const totalCount = achievements?.length ?? 0

  return (
    <>
      {/* Study Habits header */}
      <section className="flex flex-col gap-3">
        <div className="rounded-2xl bg-gradient-to-r from-amber-500/10 via-amber-500/5 to-transparent px-6 py-4 border border-amber-500/10">
          <h2 className="text-lg font-bold text-foreground">Study Habits</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Streaks, XP, focus sessions, and achievements
          </p>
        </div>

        {/* Quick stats row */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <QuickStat
            icon={Flame}
            label="Streak"
            value={`${streak?.current_streak ?? 0}d`}
            sub={`Best: ${streak?.longest_streak ?? 0}d`}
            color="text-amber-500"
          />
          <QuickStat
            icon={Zap}
            label="Level"
            value={`${xp?.level ?? 0}`}
            sub={`${xp?.total_xp ?? 0} XP total`}
            color="text-primary"
          />
          <QuickStat
            icon={Timer}
            label="Focus (7d)"
            value={`${Math.round(focusStats?.total_focus_minutes ?? 0)}m`}
            sub={`${focusStats?.completed_sessions ?? 0} sessions`}
            color="text-emerald-500"
          />
          <QuickStat
            icon={Trophy}
            label="Achievements"
            value={`${unlockedCount}/${totalCount}`}
            sub="unlocked"
            color="text-rose-500"
          />
        </div>
      </section>

      {/* XP History Chart */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">
          XP Earned (Last 30 Days)
          {xp ? (
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              +{xp.today_xp} today
            </span>
          ) : null}
        </h2>
        {historyLoading ? (
          <div className="flex flex-col gap-3">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : chartData.every((d) => d.xp === 0) ? (
          <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
            No XP earned yet. Review flashcards or create notes to start earning.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
              <Tooltip />
              <Bar dataKey="xp" name="XP" fill="#f59e0b" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </section>

      {/* Achievements grid */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Achievements</h2>
        {achievementsLoading ? (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-20 w-full rounded-lg" />
            ))}
          </div>
        ) : !achievements || achievements.length === 0 ? (
          <div className="flex h-20 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
            No achievements yet.
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
            {achievements.map((ach) => (
              <AchievementCard key={ach.key} achievement={ach} />
            ))}
          </div>
        )}
      </section>
    </>
  )
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function QuickStat({
  icon: Icon,
  label,
  value,
  sub,
  color,
}: {
  icon: typeof Trophy
  label: string
  value: string
  sub: string
  color: string
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3">
      <Icon size={20} className={color} />
      <div className="flex flex-col">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className="text-lg font-bold tabular-nums">{value}</span>
        <span className="text-[10px] text-muted-foreground">{sub}</span>
      </div>
    </div>
  )
}

function AchievementCard({ achievement: ach }: { achievement: Achievement }) {
  const unlocked = ach.unlocked_at !== null
  const Icon = ICON_MAP[ach.icon_name] ?? Trophy
  const pct = ach.progress_target > 0
    ? Math.min(100, Math.round((ach.progress_current / ach.progress_target) * 100))
    : 0

  return (
    <div
      className={cn(
        "flex flex-col gap-1.5 rounded-lg border px-3 py-2.5 transition-colors",
        unlocked
          ? "border-amber-500/30 bg-amber-500/5"
          : "border-border bg-card opacity-60",
      )}
      title={ach.description}
    >
      <div className="flex items-center gap-2">
        <Icon
          size={16}
          className={unlocked ? "text-amber-500" : "text-muted-foreground/40"}
        />
        <span className={cn("text-xs font-semibold", unlocked ? "text-foreground" : "text-muted-foreground")}>
          {ach.title}
        </span>
      </div>
      <p className="text-[10px] text-muted-foreground leading-tight">{ach.description}</p>
      {!unlocked && (
        <div className="flex items-center gap-2">
          <div className="h-1 flex-1 rounded-full bg-muted/50 overflow-hidden">
            <div
              className="h-full rounded-full bg-primary/40 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-[9px] tabular-nums text-muted-foreground">
            {ach.progress_current}/{ach.progress_target}
          </span>
        </div>
      )}
      {unlocked && (
        <span className="text-[9px] text-amber-600">
          Unlocked {new Date(ach.unlocked_at!).toLocaleDateString()}
        </span>
      )}
    </div>
  )
}
