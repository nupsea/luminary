// ---------------------------------------------------------------------------
// GoalDetailPanel (S211) -- side sheet showing a single goal's progress,
// linked sessions, and Edit / Archive / Complete / Delete actions.
// ---------------------------------------------------------------------------

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Archive, CheckCircle2, Pencil, Trash2 } from "lucide-react"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { GoalProgressBar } from "./GoalProgressBar"
import { GoalEditDialog } from "./GoalEditDialog"
import { GOAL_TYPE_ICON, GOAL_TYPE_LABEL } from "./goalTypeMeta"
import {
  type Goal,
  type GoalProgress,
  type LinkedSession,
  archiveGoal,
  completeGoal,
  deleteGoal,
  getGoal,
  getGoalProgress,
  getLinkedSessions,
} from "@/lib/goalsApi"

interface Props {
  goalId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

function StatusBadge({ status }: { status: Goal["status"] }) {
  const cls: Record<Goal["status"], string> = {
    active: "bg-blue-100 text-blue-800 border-blue-200",
    paused: "bg-amber-100 text-amber-800 border-amber-200",
    completed: "bg-green-100 text-green-800 border-green-200",
    archived: "bg-muted text-muted-foreground border-border",
  }
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${cls[status]}`}
    >
      {status}
    </span>
  )
}

export function GoalDetailPanel({ goalId, open, onOpenChange }: Props) {
  const qc = useQueryClient()
  const [editOpen, setEditOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const goalQuery = useQuery<Goal>({
    queryKey: ["goal", goalId],
    queryFn: () => {
      if (!goalId) throw new Error("No goal id")
      return getGoal(goalId)
    },
    enabled: open && !!goalId,
    staleTime: 30_000,
  })

  const progressQuery = useQuery<GoalProgress>({
    queryKey: ["goal-progress", goalId],
    queryFn: () => {
      if (!goalId) throw new Error("No goal id")
      return getGoalProgress(goalId)
    },
    enabled: open && !!goalId,
    staleTime: 30_000,
  })

  const sessionsQuery = useQuery<LinkedSession[]>({
    queryKey: ["goal-sessions", goalId],
    queryFn: () => {
      if (!goalId) throw new Error("No goal id")
      return getLinkedSessions(goalId, 20)
    },
    enabled: open && !!goalId,
    staleTime: 30_000,
  })

  function invalidateAll() {
    void qc.invalidateQueries({ queryKey: ["goals"] })
    if (goalId) {
      void qc.invalidateQueries({ queryKey: ["goal", goalId] })
      void qc.invalidateQueries({ queryKey: ["goal-progress", goalId] })
      void qc.invalidateQueries({ queryKey: ["goal-sessions", goalId] })
    }
  }

  const archiveMutation = useMutation({
    mutationFn: () => {
      if (!goalId) throw new Error("No goal id")
      return archiveGoal(goalId)
    },
    onSuccess: invalidateAll,
  })

  const completeMutation = useMutation({
    mutationFn: () => {
      if (!goalId) throw new Error("No goal id")
      return completeGoal(goalId)
    },
    onSuccess: invalidateAll,
  })

  const deleteMutation = useMutation({
    mutationFn: () => {
      if (!goalId) throw new Error("No goal id")
      return deleteGoal(goalId)
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["goals"] })
      onOpenChange(false)
    },
  })

  const goal = goalQuery.data
  const isLoading = goalQuery.isLoading || progressQuery.isLoading

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex flex-col overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Goal details</SheetTitle>
          <SheetDescription>
            Track progress and manage this learning goal.
          </SheetDescription>
        </SheetHeader>

        {isLoading ? (
          <div className="mt-4 flex flex-col gap-3" aria-label="Loading goal">
            <div className="h-5 w-1/2 animate-pulse rounded bg-muted" />
            <div className="h-3 w-2/3 animate-pulse rounded bg-muted" />
            <div className="h-2 w-full animate-pulse rounded-full bg-muted" />
          </div>
        ) : goalQuery.isError || !goal ? (
          <div
            role="alert"
            className="mt-4 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive"
          >
            Could not load goal.
          </div>
        ) : (
          <div className="mt-4 flex flex-col gap-5">
            {/* Header */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2 flex-wrap">
                {(() => {
                  const TypeIcon = GOAL_TYPE_ICON[goal.goal_type]
                  return (
                    <span className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/50 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                      <TypeIcon size={11} aria-hidden="true" />
                      {GOAL_TYPE_LABEL[goal.goal_type]}
                    </span>
                  )
                })()}
                <StatusBadge status={goal.status} />
              </div>
              <h2 className="text-lg font-semibold text-foreground">
                {goal.title}
              </h2>
              {goal.description && (
                <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                  {goal.description}
                </p>
              )}
            </div>

            {/* Progress */}
            <section className="flex flex-col gap-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Progress
              </h3>
              <GoalProgressBar
                goal={goal}
                metrics={progressQuery.data?.metrics}
                loading={progressQuery.isLoading}
                errored={progressQuery.isError}
              />
              {progressQuery.data && (
                <div className="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground mt-1">
                  <div>
                    Sessions completed:{" "}
                    <span className="font-mono text-foreground">
                      {progressQuery.data.metrics.sessions_completed ?? 0}
                    </span>
                  </div>
                  {goal.goal_type === "recall" &&
                    progressQuery.data.metrics.avg_retention !== null &&
                    progressQuery.data.metrics.avg_retention !== undefined && (
                      <div>
                        Avg retention:{" "}
                        <span className="font-mono text-foreground">
                          {(
                            progressQuery.data.metrics.avg_retention * 100
                          ).toFixed(0)}
                          %
                        </span>
                      </div>
                    )}
                </div>
              )}
            </section>

            {/* Linked sessions */}
            <section className="flex flex-col gap-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Linked sessions
              </h3>
              {sessionsQuery.isLoading ? (
                <div className="flex flex-col gap-1">
                  <div className="h-4 w-full animate-pulse rounded bg-muted" />
                  <div className="h-4 w-full animate-pulse rounded bg-muted" />
                </div>
              ) : sessionsQuery.isError ? (
                <div role="alert" className="text-[11px] text-destructive">
                  Could not load sessions.
                </div>
              ) : !sessionsQuery.data || sessionsQuery.data.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No sessions linked yet. Start a focus session with this goal attached.
                </p>
              ) : (
                <ul className="flex flex-col gap-1.5 max-h-64 overflow-y-auto">
                  {sessionsQuery.data.map((s) => (
                    <li
                      key={s.id}
                      className="flex items-center justify-between rounded border border-border bg-card/40 px-2 py-1 text-[11px]"
                    >
                      <span className="font-mono text-muted-foreground">
                        {new Date(s.started_at).toLocaleString()}
                      </span>
                      <span className="flex items-center gap-2">
                        <span className="text-muted-foreground">{s.surface}</span>
                        <span className="font-mono text-foreground">
                          {s.focus_minutes}m
                        </span>
                        <span
                          className={`text-[10px] uppercase tracking-wide ${
                            s.status === "completed"
                              ? "text-emerald-700"
                              : "text-muted-foreground"
                          }`}
                        >
                          {s.status}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Actions */}
            <section className="flex flex-col gap-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Actions
              </h3>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setEditOpen(true)}
                  disabled={goal.status === "archived"}
                  className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-xs hover:bg-accent disabled:opacity-50"
                >
                  <Pencil size={12} />
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => completeMutation.mutate()}
                  disabled={
                    completeMutation.isPending ||
                    goal.status === "completed" ||
                    goal.status === "archived"
                  }
                  className="inline-flex items-center gap-1 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs text-emerald-800 hover:bg-emerald-100 disabled:opacity-50"
                >
                  <CheckCircle2 size={12} />
                  Complete
                </button>
                <button
                  type="button"
                  onClick={() => archiveMutation.mutate()}
                  disabled={
                    archiveMutation.isPending || goal.status === "archived"
                  }
                  className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs text-amber-800 hover:bg-amber-100 disabled:opacity-50"
                >
                  <Archive size={12} />
                  Archive
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmDelete(true)}
                  disabled={deleteMutation.isPending}
                  className="inline-flex items-center gap-1 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-1.5 text-xs text-destructive hover:bg-destructive/10 disabled:opacity-50"
                >
                  <Trash2 size={12} />
                  Delete
                </button>
              </div>

              {confirmDelete && (
                <div className="mt-2 flex flex-col gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3">
                  <p className="text-xs text-destructive">
                    Delete this goal? Linked focus sessions will be unlinked but
                    not deleted.
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setConfirmDelete(false)}
                      className="rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-accent"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteMutation.mutate()}
                      disabled={deleteMutation.isPending}
                      className="rounded-md bg-destructive px-2 py-1 text-xs font-semibold text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </section>
          </div>
        )}

        <GoalEditDialog
          goal={goal ?? null}
          open={editOpen}
          onOpenChange={setEditOpen}
        />
      </SheetContent>
    </Sheet>
  )
}
