// ---------------------------------------------------------------------------
// goalsApi (S211) -- typed wrappers for the S210 typed-goals backend.
// Uses the shared apiClient (#12 standardisation).
// ---------------------------------------------------------------------------

import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/apiClient"

export type GoalType = "studying" | "read" | "recall" | "write" | "explore"
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
  surface_minutes?: Record<string, number>
  surface_sessions?: Record<string, number>
  metadata?: {
    document_id: string | null
    deck_id: string | null
    collection_id: string | null
  }
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

export const listGoals = (status?: GoalStatus): Promise<Goal[]> =>
  apiGet<Goal[]>("/goals", { status })

export const getGoal = (id: string): Promise<Goal> =>
  apiGet<Goal>(`/goals/${encodeURIComponent(id)}`)

export const createGoal = (args: CreateGoalArgs): Promise<Goal> =>
  apiPost<Goal>("/goals", args)

export const updateGoal = (id: string, args: UpdateGoalArgs): Promise<Goal> =>
  apiPatch<Goal>(`/goals/${encodeURIComponent(id)}`, args)

export const archiveGoal = (id: string): Promise<Goal> =>
  apiPost<Goal>(`/goals/${encodeURIComponent(id)}/archive`)

export const completeGoal = (id: string): Promise<Goal> =>
  apiPost<Goal>(`/goals/${encodeURIComponent(id)}/complete`)

export const deleteGoal = (id: string): Promise<void> =>
  apiDelete(`/goals/${encodeURIComponent(id)}`)

export const getGoalProgress = (id: string): Promise<GoalProgress> =>
  apiGet<GoalProgress>(`/goals/${encodeURIComponent(id)}/progress`)

export const getLinkedSessions = (
  id: string,
  limit = 20,
): Promise<LinkedSession[]> =>
  apiGet<LinkedSession[]>(`/goals/${encodeURIComponent(id)}/sessions`, { limit })
