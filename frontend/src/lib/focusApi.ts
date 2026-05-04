// ---------------------------------------------------------------------------
// focusApi -- thin fetch wrappers for /pomodoro/* endpoints (S208) used by the
// global FocusTimerPill (S209). All methods return parsed JSON or null on 204.
// ---------------------------------------------------------------------------

import { API_BASE } from "@/lib/config"
import type { Surface } from "@/lib/focusUtils"

export interface PomodoroSession {
  id: string
  started_at: string
  completed_at: string | null
  focus_minutes: number
  break_minutes: number
  status: "active" | "paused" | "completed" | "abandoned"
  surface: Surface
  document_id: string | null
  deck_id: string | null
  goal_id: string | null
  paused_at: string | null
  pause_accumulated_seconds: number
  created_at: string
}

export interface PomodoroStats {
  today_count: number
  streak_days: number
  total_completed: number
}

export interface StartArgs {
  focus_minutes: number
  break_minutes: number
  surface: Surface
  document_id?: string | null
  deck_id?: string | null
  goal_id?: string | null
}

export interface ActiveSessionConflict {
  status: 409
  existing_session_id: string
}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => "")
    throw new Error(`HTTP ${res.status}: ${body || res.statusText}`)
  }
  return (await res.json()) as T
}

export async function startSession(args: StartArgs): Promise<PomodoroSession | ActiveSessionConflict> {
  const res = await fetch(`${API_BASE}/pomodoro/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  })
  if (res.status === 409) {
    const body = (await res.json().catch(() => ({}))) as {
      detail?: { existing_session_id?: string }
    }
    return {
      status: 409,
      existing_session_id: body.detail?.existing_session_id ?? "",
    }
  }
  return asJson<PomodoroSession>(res)
}

export async function pauseSession(id: string): Promise<PomodoroSession> {
  const res = await fetch(`${API_BASE}/pomodoro/${id}/pause`, { method: "POST" })
  return asJson<PomodoroSession>(res)
}

export async function resumeSession(id: string): Promise<PomodoroSession> {
  const res = await fetch(`${API_BASE}/pomodoro/${id}/resume`, { method: "POST" })
  return asJson<PomodoroSession>(res)
}

export async function completeSession(id: string): Promise<PomodoroSession> {
  const res = await fetch(`${API_BASE}/pomodoro/${id}/complete`, { method: "POST" })
  return asJson<PomodoroSession>(res)
}

export async function abandonSession(id: string): Promise<PomodoroSession> {
  const res = await fetch(`${API_BASE}/pomodoro/${id}/abandon`, { method: "POST" })
  return asJson<PomodoroSession>(res)
}

// Returns null on 204 (no active or paused session).
export async function getActiveSession(): Promise<PomodoroSession | null> {
  const res = await fetch(`${API_BASE}/pomodoro/active`)
  if (res.status === 204) return null
  return asJson<PomodoroSession>(res)
}

export async function getStats(): Promise<PomodoroStats> {
  const res = await fetch(`${API_BASE}/pomodoro/stats`)
  return asJson<PomodoroStats>(res)
}
