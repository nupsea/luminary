import { useQuery } from "@tanstack/react-query"
import { Flame, Zap } from "lucide-react"
import { API_BASE } from "@/lib/config"
import { cn } from "@/lib/utils"

interface StreakData {
  current_streak: number
  longest_streak: number
  studied_today: boolean
  freezes_available: number
}

interface XPData {
  total_xp: number
  level: number
  xp_to_next_level: number
  today_xp: number
}

async function fetchStreak(): Promise<StreakData> {
  const res = await fetch(`${API_BASE}/engagement/streak`)
  if (!res.ok) throw new Error("Failed to fetch streak")
  return res.json()
}

async function fetchXP(): Promise<XPData> {
  const res = await fetch(`${API_BASE}/engagement/xp`)
  if (!res.ok) throw new Error("Failed to fetch XP")
  return res.json()
}

export function StreakXPWidget() {
  const { data: streak } = useQuery({
    queryKey: ["engagement-streak"],
    queryFn: fetchStreak,
    staleTime: 60_000,
    retry: 1,
  })

  const { data: xp } = useQuery({
    queryKey: ["engagement-xp"],
    queryFn: fetchXP,
    staleTime: 60_000,
    retry: 1,
  })

  if (!streak && !xp) return null

  const streakCount = streak?.current_streak ?? 0
  const level = xp?.level ?? 0
  const totalXP = xp?.total_xp ?? 0
  const xpToNext = xp?.xp_to_next_level ?? 100
  const progressPct = Math.min(
    100,
    Math.round(((totalXP) / (totalXP + xpToNext)) * 100)
  )

  return (
    <div className="flex flex-col items-center gap-1.5 px-1">
      {/* Streak */}
      <div
        className="flex items-center gap-1"
        title={`${streakCount}-day streak${streak?.freezes_available ? ` (${streak.freezes_available} freezes)` : ""}`}
      >
        <Flame
          size={14}
          className={cn(
            "transition-colors",
            streakCount === 0 && "text-muted-foreground/40",
            streakCount > 0 && streakCount < 7 && "text-amber-500",
            streakCount >= 7 && "text-orange-500",
          )}
        />
        <span
          className={cn(
            "text-[10px] font-semibold tabular-nums",
            streakCount === 0 && "text-muted-foreground/40",
            streakCount > 0 && "text-foreground/70",
          )}
        >
          {streakCount}
        </span>
      </div>

      {/* XP / Level */}
      <div
        className="flex flex-col items-center gap-0.5"
        title={`Level ${level} -- ${totalXP} XP total, ${xpToNext} to next level. Today: +${xp?.today_xp ?? 0}`}
      >
        <div className="flex items-center gap-0.5">
          <Zap size={10} className="text-primary/60" />
          <span className="text-[9px] font-medium text-foreground/60">
            Lv.{level}
          </span>
        </div>
        {/* XP progress bar */}
        <div className="h-1 w-10 rounded-full bg-muted/50 overflow-hidden">
          <div
            className="h-full rounded-full bg-primary/60 transition-all duration-500"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>
    </div>
  )
}
