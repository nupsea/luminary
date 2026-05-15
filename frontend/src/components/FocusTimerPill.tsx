// ---------------------------------------------------------------------------
// FocusTimerPill -- global focus timer pill mounted in the app header.
// Drives a Pomodoro session against the /pomodoro/* endpoints.
// ---------------------------------------------------------------------------

import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  ChevronDown,
  Pause,
  Play,
  Square,
  Volume2,
  VolumeX,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useLocation } from "react-router-dom"
import { Skeleton } from "@/components/ui/skeleton"
import { logger } from "@/lib/logger"
import {
  abandonSession,
  completeSession,
  getActiveSession,
  getStats,
  pauseSession,
  resumeSession,
  startSession,
} from "@/lib/focusApi"
import type { PomodoroStats } from "@/lib/focusApi"
import { formatMmSs, inferSurfaceFromPath, isValidMinutes } from "@/lib/focusUtils"
import { cn } from "@/lib/utils"
import {
  clearSnapshot,
  useFocusStore,
  writeSnapshot,
} from "@/store/focus"
import { type Goal, listGoals } from "@/lib/goalsApi"
import {
  GOAL_TYPE_LABEL,
  surfaceMismatchWarning,
} from "@/components/goals/goalTypeMeta"

const POMODORO_STATS_KEY = ["pomodoro-stats"] as const

function playChime(volume = 0.25): void {
  if (typeof window === "undefined") return
  const Ctor = window.AudioContext ?? (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!Ctor) return
  try {
    const ctx = new Ctor()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.type = "sine"
    osc.frequency.value = 880
    gain.gain.value = volume
    osc.connect(gain).connect(ctx.destination)
    osc.start()
    // Two short beeps, total ~600ms, then close the context.
    osc.frequency.setValueAtTime(880, ctx.currentTime)
    osc.frequency.setValueAtTime(660, ctx.currentTime + 0.25)
    gain.gain.setValueAtTime(volume, ctx.currentTime)
    gain.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.6)
    osc.stop(ctx.currentTime + 0.62)
    osc.onended = () => {
      try {
        void ctx.close()
      } catch {
        // ignore
      }
    }
  } catch (err) {
    logger.warn("[FocusTimerPill] chime failed", String(err))
  }
}

export function FocusTimerPill() {
  const location = useLocation()
  const qc = useQueryClient()

  const sessionId = useFocusStore((s) => s.sessionId)
  const phase = useFocusStore((s) => s.phase)
  const secondsLeft = useFocusStore((s) => s.secondsLeft)
  const focusMinutes = useFocusStore((s) => s.focusMinutes)
  const breakMinutes = useFocusStore((s) => s.breakMinutes)
  const surface = useFocusStore((s) => s.surface)
  const muted = useFocusStore((s) => s.muted)
  const errorMessage = useFocusStore((s) => s.errorMessage)
  const goalId = useFocusStore((s) => s.goalId)

  const enterFocus = useFocusStore((s) => s.enterFocus)
  const enterPaused = useFocusStore((s) => s.enterPaused)
  const enterBreak = useFocusStore((s) => s.enterBreak)
  const enterIdle = useFocusStore((s) => s.enterIdle)
  const tick = useFocusStore((s) => s.tick)
  const setFocusMinutes = useFocusStore((s) => s.setFocusMinutes)
  const setBreakMinutes = useFocusStore((s) => s.setBreakMinutes)
  const setMuted = useFocusStore((s) => s.setMuted)
  const setSurface = useFocusStore((s) => s.setSurface)
  const setError = useFocusStore((s) => s.setError)
  const setGoalId = useFocusStore((s) => s.setGoalId)
  const hydrate = useFocusStore((s) => s.hydrate)

  const [popoverOpen, setPopoverOpen] = useState(false)
  const [hydrated, setHydrated] = useState(false)
  // Latch to avoid double-firing /complete when secondsLeft reaches 0.
  const completingRef = useRef(false)

  const stats = useQuery<PomodoroStats>({
    queryKey: POMODORO_STATS_KEY,
    queryFn: getStats,
    staleTime: 60_000,
    retry: 1,
  })

  // active goals for the Attach-to-goal select. Only fetched when the
  // popover is open to keep idle traffic minimal.
  const goalsQuery = useQuery<Goal[]>({
    queryKey: ["goals", "active"],
    queryFn: () => listGoals("active"),
    staleTime: 30_000,
    enabled: popoverOpen,
  })

  const selectedGoal: Goal | null = (goalsQuery.data ?? []).find(
    (g) => g.id === goalId,
  ) ?? null
  const mismatchWarning = selectedGoal
    ? surfaceMismatchWarning(selectedGoal.goal_type, surface)
    : null

  // ---------------------------------------------------------------------
  // Mount-time hydration: reconcile localStorage + GET /pomodoro/active.
  // ---------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const active = await getActiveSession()
        if (cancelled) return
        if (active && (active.status === "active" || active.status === "paused")) {
          // Compute remaining seconds: focus_minutes*60 - (now - started_at) + paused_accum.
          const startedMs = Date.parse(active.started_at)
          const elapsedSec = Math.max(
            0,
            Math.floor((Date.now() - startedMs) / 1000) - active.pause_accumulated_seconds,
          )
          const remaining = Math.max(0, active.focus_minutes * 60 - elapsedSec)
          hydrate({
            sessionId: active.id,
            phase: active.status === "active" ? "focus" : "paused",
            secondsLeft: remaining,
            focusMinutes: active.focus_minutes,
            breakMinutes: active.break_minutes,
            surface: active.surface,
            goalId: active.goal_id,
            lastTickAt: Date.now(),
          })
        } else {
          // No server session -- reset local snapshot to avoid stale ids.
          clearSnapshot()
          enterIdle()
        }
      } catch (err) {
        logger.warn("[FocusTimerPill] hydrate failed", String(err))
      } finally {
        if (!cancelled) setHydrated(true)
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ---------------------------------------------------------------------
  // Surface auto-detection from active route.
  // ---------------------------------------------------------------------
  useEffect(() => {
    setSurface(inferSurfaceFromPath(location.pathname))
  }, [location.pathname, setSurface])

  // ---------------------------------------------------------------------
  // Persist snapshot to localStorage on every state change.
  // ---------------------------------------------------------------------
  useEffect(() => {
    writeSnapshot({
      sessionId,
      phase,
      secondsLeft,
      focusMinutes,
      breakMinutes,
      surface,
      goalId,
      muted,
      lastTickAt: Date.now(),
    })
  }, [sessionId, phase, secondsLeft, focusMinutes, breakMinutes, surface, goalId, muted])

  // ---------------------------------------------------------------------
  // Tick interval -- runs while phase is focus or break.
  // ---------------------------------------------------------------------
  useEffect(() => {
    if (phase !== "focus" && phase !== "break") return
    const id = window.setInterval(() => {
      tick()
    }, 1000)
    return () => window.clearInterval(id)
  }, [phase, tick])

  // ---------------------------------------------------------------------
  // Auto-complete focus -> break, and break -> idle.
  // ---------------------------------------------------------------------
  useEffect(() => {
    if (secondsLeft > 0) return
    if (phase === "focus" && sessionId && !completingRef.current) {
      completingRef.current = true
      void (async () => {
        try {
          await completeSession(sessionId)
          if (!muted) playChime()
          enterBreak(breakMinutes * 60)
          await qc.invalidateQueries({ queryKey: POMODORO_STATS_KEY })
          // refresh goal lists/progress when a session completes so the
          // open GoalsList and GoalDetailPanel reflect the new state.
          await qc.invalidateQueries({ queryKey: ["goals"] })
          if (goalId) {
            await qc.invalidateQueries({ queryKey: ["goal-progress", goalId] })
            await qc.invalidateQueries({ queryKey: ["goal-sessions", goalId] })
          }
        } catch (err) {
          setError(`Could not complete session: ${String(err)}`)
        } finally {
          completingRef.current = false
        }
      })()
    } else if (phase === "break") {
      enterIdle()
    }
  }, [secondsLeft, phase, sessionId, muted, breakMinutes, qc, enterBreak, enterIdle, setError, goalId])

  // ---------------------------------------------------------------------
  // Action handlers
  // ---------------------------------------------------------------------
  async function handleStart() {
    if (!isValidMinutes(focusMinutes) || !isValidMinutes(breakMinutes)) {
      setError("Focus and break minutes must be 1..120")
      return
    }
    setError(null)
    try {
      const res = await startSession({
        focus_minutes: focusMinutes,
        break_minutes: breakMinutes,
        surface,
        goal_id: goalId,
      })
      if ("status" in res && res.status === 409) {
        setError(`A session is already active (id ${res.existing_session_id}). Refresh to recover.`)
        return
      }
      enterFocus(res.id, res.focus_minutes * 60)
      setPopoverOpen(false)
    } catch (err) {
      setError(`Could not start session: ${String(err)}`)
    }
  }

  async function handlePause() {
    if (!sessionId) return
    setError(null)
    try {
      await pauseSession(sessionId)
      enterPaused()
    } catch (err) {
      setError(`Could not pause: ${String(err)}`)
    }
  }

  async function handleResume() {
    if (!sessionId) return
    setError(null)
    try {
      await resumeSession(sessionId)
      // Phase back to focus, secondsLeft preserved.
      useFocusStore.setState({ phase: "focus", lastTickAt: Date.now() })
    } catch (err) {
      setError(`Could not resume: ${String(err)}`)
    }
  }

  async function handleStop() {
    if (phase === "break") {
      enterIdle()
      return
    }
    if (!sessionId) {
      enterIdle()
      return
    }
    setError(null)
    try {
      await abandonSession(sessionId)
      enterIdle()
      await qc.invalidateQueries({ queryKey: POMODORO_STATS_KEY })
    } catch (err) {
      setError(`Could not stop: ${String(err)}`)
    }
  }

  // ---------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------
  if (!hydrated) {
    return (
      <div className="flex items-center gap-2" aria-label="Focus timer loading">
        <Skeleton className="h-8 w-32 rounded-full" />
      </div>
    )
  }

  const phaseLabel: Record<typeof phase, string> = {
    idle: "Ready to focus",
    focus: "Focus",
    paused: "Paused",
    break: "Break",
  }

  const startDisabled = !isValidMinutes(focusMinutes) || !isValidMinutes(breakMinutes)

  return (
    <div className="relative flex flex-col items-end gap-1">
      <div
        className={cn(
          "flex items-center gap-1 rounded-full border px-2 py-1 text-xs shadow-sm transition-colors bg-background",
          phase === "focus" && "border-primary/60 bg-primary/5",
          phase === "paused" && "border-amber-400/60 bg-amber-50 dark:bg-amber-950/20",
          phase === "break" && "border-emerald-400/60 bg-emerald-50 dark:bg-emerald-950/20",
          phase === "idle" && "border-border",
        )}
        role="group"
        aria-label="Focus timer"
      >
        <span
          className="font-mono tabular-nums text-foreground/90 px-1"
          aria-label={`Time remaining ${formatMmSs(secondsLeft)}`}
        >
          {formatMmSs(secondsLeft)}
        </span>
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground hidden sm:inline">
          {phaseLabel[phase]}
        </span>

        {phase === "idle" && (
          <button
            type="button"
            onClick={() => void handleStart()}
            disabled={startDisabled}
            className="ml-1 rounded-full bg-primary px-2 py-0.5 text-[11px] font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            title="Start focus session"
          >
            Start
          </button>
        )}

        {phase === "focus" && (
          <>
            <button
              type="button"
              onClick={() => void handlePause()}
              className="ml-1 rounded-full p-1 text-foreground/70 hover:bg-accent"
              title="Pause"
              aria-label="Pause focus session"
            >
              <Pause size={12} />
            </button>
            <button
              type="button"
              onClick={() => void handleStop()}
              className="rounded-full p-1 text-foreground/70 hover:bg-accent"
              title="Stop"
              aria-label="Stop focus session"
            >
              <Square size={12} />
            </button>
          </>
        )}

        {phase === "paused" && (
          <>
            <button
              type="button"
              onClick={() => void handleResume()}
              className="ml-1 rounded-full p-1 text-foreground/70 hover:bg-accent"
              title="Resume"
              aria-label="Resume focus session"
            >
              <Play size={12} />
            </button>
            <button
              type="button"
              onClick={() => void handleStop()}
              className="rounded-full p-1 text-foreground/70 hover:bg-accent"
              title="Stop"
              aria-label="Stop focus session"
            >
              <Square size={12} />
            </button>
          </>
        )}

        {phase === "break" && (
          <button
            type="button"
            onClick={() => void handleStop()}
            className="ml-1 rounded-full p-1 text-foreground/70 hover:bg-accent"
            title="End break"
            aria-label="End break"
          >
            <Square size={12} />
          </button>
        )}

        <button
          type="button"
          onClick={() => setPopoverOpen((o) => !o)}
          aria-label="Open focus stats"
          aria-expanded={popoverOpen}
          className="ml-0.5 rounded-full p-1 text-foreground/60 hover:bg-accent"
          title="Stats and settings"
        >
          <ChevronDown size={12} />
        </button>
      </div>

      {errorMessage && (
        <div
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/5 px-2 py-1 text-[11px] text-destructive max-w-xs"
        >
          {errorMessage}
        </div>
      )}

      {popoverOpen && (
        <div
          role="dialog"
          aria-label="Focus stats and settings"
          className="absolute right-0 top-full z-40 mt-2 w-72 rounded-lg border border-border bg-background p-3 shadow-lg"
        >
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-foreground">Focus stats</h3>
            <button
              type="button"
              onClick={() => setMuted(!muted)}
              className="rounded-full p-1 text-foreground/60 hover:bg-accent"
              title={muted ? "Unmute chime" : "Mute chime"}
              aria-label={muted ? "Unmute chime" : "Mute chime"}
            >
              {muted ? <VolumeX size={12} /> : <Volume2 size={12} />}
            </button>
          </div>

          {stats.isError ? (
            <div
              role="alert"
              className="mt-2 rounded-md border border-destructive/40 bg-destructive/5 px-2 py-1 text-[11px] text-destructive"
            >
              Could not load focus stats.
            </div>
          ) : (
            <div className="mt-2 grid grid-cols-3 gap-2 text-center">
              <StatBlock label="Today" value={stats.data?.today_count} loading={stats.isLoading} />
              <StatBlock label="Streak" value={stats.data?.streak_days} loading={stats.isLoading} />
              <StatBlock label="Total" value={stats.data?.total_completed} loading={stats.isLoading} />
            </div>
          )}

          <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
            <label className="flex flex-col gap-0.5">
              <span className="text-muted-foreground">Focus min</span>
              <input
                type="number"
                min={1}
                max={120}
                value={focusMinutes}
                onChange={(e) => {
                  const n = Number(e.target.value)
                  setFocusMinutes(Number.isFinite(n) ? Math.floor(n) : focusMinutes)
                }}
                disabled={phase !== "idle"}
                className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs"
              />
            </label>
            <label className="flex flex-col gap-0.5">
              <span className="text-muted-foreground">Break min</span>
              <input
                type="number"
                min={1}
                max={120}
                value={breakMinutes}
                onChange={(e) => {
                  const n = Number(e.target.value)
                  setBreakMinutes(Number.isFinite(n) ? Math.floor(n) : breakMinutes)
                }}
                disabled={phase !== "idle"}
                className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs"
              />
            </label>
          </div>

          <p className="mt-2 text-[10px] text-muted-foreground">
            Surface: <span className="font-mono">{surface}</span>
            {" -- inferred from the active tab."}
          </p>

          {/* Attach-to-goal select */}
          <div className="mt-3 flex flex-col gap-1">
            <label
              htmlFor="focus-attach-goal"
              className="text-[10px] uppercase tracking-wide text-muted-foreground"
            >
              Attach to goal
            </label>
            <select
              id="focus-attach-goal"
              value={goalId ?? ""}
              onChange={(e) => setGoalId(e.target.value || null)}
              disabled={phase !== "idle" || goalsQuery.isLoading}
              className="rounded-md border border-border bg-background px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            >
              <option value="">No goal</option>
              {(goalsQuery.data ?? []).map((g) => (
                <option key={g.id} value={g.id}>
                  {g.title} ({GOAL_TYPE_LABEL[g.goal_type]})
                </option>
              ))}
            </select>
            {goalsQuery.isError && (
              <span role="alert" className="text-[10px] text-destructive">
                Could not load goals.
              </span>
            )}
            {mismatchWarning && (
              <div
                role="alert"
                className="mt-1 flex items-start gap-1 rounded-md border border-amber-300/60 bg-amber-50 px-2 py-1 text-[10px] text-amber-800 dark:bg-amber-950/20 dark:text-amber-200"
              >
                <AlertTriangle size={10} className="mt-[2px] shrink-0" />
                <span>{mismatchWarning}</span>
              </div>
            )}
          </div>

          {phase === "idle" && (
            <button
              type="button"
              onClick={() => void handleStart()}
              disabled={startDisabled}
              className="mt-3 w-full rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              Start focus session
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function StatBlock({ label, value, loading }: { label: string; value: number | undefined; loading: boolean }) {
  return (
    <div className="rounded-md bg-muted/40 px-2 py-1">
      <div className="text-[9px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold tabular-nums text-foreground">
        {loading ? <Skeleton className="mx-auto h-4 w-6" /> : (value ?? 0)}
      </div>
    </div>
  )
}
