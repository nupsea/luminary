// ---------------------------------------------------------------------------
// goalsApi (S211) -- typed fetch wrappers for the S210 typed-goals backend.
// ---------------------------------------------------------------------------

import { API_BASE } from "@/lib/config"

export type GoalType = "read" | "recall" | "write" | "explore"
export type TargetUnit = "minutes" | "pages" | "cards" | "notes" | "turns"
export type GoalStatus = "active" | "paused" | "completed" | "archived"

export interface Goal {
  id: string
  title: string
  description: string | null
  goal_type: GoalType
  target_value: number | null
  target_unit: TargetUnit | null
  document_id: string | null
  deck_id: string | null
  collection_id: string | null
  status: GoalStatus
  created_at: string
  completed_at: string | null
}

export interface GoalProgressMetrics {
  minutes_focused?: number
  cards_reviewed?: number
  avg_retention?: number | null
  notes_created?: number
  turns?: number
  sessions_completed?: number
  completed_pct?: number
}

export interface GoalProgress {
  goal_id: string
  goal_type: GoalType
  metrics: GoalProgressMetrics
}

export interface LinkedSession {
  id: string
  started_at: string
  completed_at: string | null
  status: string
  surface: string
  focus_minutes: number
}

export interface CreateGoalArgs {
  title: string
  goal_type: GoalType
  target_value?: number | null
  target_unit?: TargetUnit | null
  document_id?: string | null
  deck_id?: string | null
  collection_id?: string | null
  description?: string | null
}

export interface UpdateGoalArgs {
  title?: string | null
  description?: string | null
  target_value?: number | null
  target_unit?: TargetUnit | null
}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => "")
    throw new Error(`HTTP ${res.status}: ${body || res.statusText}`)
  }
  return (await res.json()) as T
}

export async function listGoals(status?: GoalStatus): Promise<Goal[]> {
  const url = new URL(`${API_BASE}/goals`)
  if (status) url.searchParams.set("status", status)
  const res = await fetch(url.toString())
  return asJson<Goal[]>(res)
}

export async function getGoal(id: string): Promise<Goal> {
  const res = await fetch(`${API_BASE}/goals/${encodeURIComponent(id)}`)
  return asJson<Goal>(res)
}

export async function createGoal(args: CreateGoalArgs): Promise<Goal> {
  const res = await fetch(`${API_BASE}/goals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  })
  return asJson<Goal>(res)
}

export async function updateGoal(id: string, args: UpdateGoalArgs): Promise<Goal> {
  const res = await fetch(`${API_BASE}/goals/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  })
  return asJson<Goal>(res)
}

export async function archiveGoal(id: string): Promise<Goal> {
  const res = await fetch(`${API_BASE}/goals/${encodeURIComponent(id)}/archive`, {
    method: "POST",
  })
  return asJson<Goal>(res)
}

export async function completeGoal(id: string): Promise<Goal> {
  const res = await fetch(`${API_BASE}/goals/${encodeURIComponent(id)}/complete`, {
    method: "POST",
  })
  return asJson<Goal>(res)
}

export async function deleteGoal(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/goals/${encodeURIComponent(id)}`, {
    method: "DELETE",
  })
  if (!res.ok && res.status !== 204) {
    const body = await res.text().catch(() => "")
    throw new Error(`HTTP ${res.status}: ${body || res.statusText}`)
  }
}

export async function getGoalProgress(id: string): Promise<GoalProgress> {
  const res = await fetch(`${API_BASE}/goals/${encodeURIComponent(id)}/progress`)
  return asJson<GoalProgress>(res)
}

export async function getLinkedSessions(
  id: string,
  limit = 20,
): Promise<LinkedSession[]> {
  const url = new URL(`${API_BASE}/goals/${encodeURIComponent(id)}/sessions`)
  url.searchParams.set("limit", String(limit))
  const res = await fetch(url.toString())
  return asJson<LinkedSession[]>(res)
}
