// ---------------------------------------------------------------------------
// GoalEditDialog (S211) -- edit title, description, and target value+unit.
// Other immutable fields (goal_type, document_id, deck_id, collection_id)
// follow S210 service rules and are not editable.
// ---------------------------------------------------------------------------

import { useEffect, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  type Goal,
  type TargetUnit,
  type UpdateGoalArgs,
  updateGoal,
} from "@/lib/goalsApi"

const TARGET_UNITS: TargetUnit[] = [
  "minutes",
  "pages",
  "cards",
  "notes",
  "turns",
]

interface Props {
  goal: Goal | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function GoalEditDialog({ goal, open, onOpenChange }: Props) {
  const qc = useQueryClient()
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [targetValue, setTargetValue] = useState<string>("")
  const [targetUnit, setTargetUnit] = useState<TargetUnit>("minutes")
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open && goal) {
      setTitle(goal.title)
      setDescription(goal.description ?? "")
      setTargetValue(goal.target_value !== null ? String(goal.target_value) : "")
      setTargetUnit((goal.target_unit ?? "minutes") as TargetUnit)
      setError(null)
    }
  }, [open, goal])

  const mutation = useMutation({
    mutationFn: (args: UpdateGoalArgs) => {
      if (!goal) throw new Error("No goal to update")
      return updateGoal(goal.id, args)
    },
    onSuccess: (updated) => {
      void qc.invalidateQueries({ queryKey: ["goals"] })
      void qc.invalidateQueries({ queryKey: ["goal", updated.id] })
      onOpenChange(false)
    },
    onError: (err: Error) => setError(err.message || "Could not update goal"),
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    const cleanTitle = title.trim()
    if (!cleanTitle) {
      setError("Title is required")
      return
    }
    let tvNum: number | null = null
    const tv = targetValue.trim()
    if (tv !== "") {
      const n = Number(tv)
      if (!Number.isFinite(n) || !Number.isInteger(n) || n < 1) {
        setError("Target value must be a positive integer")
        return
      }
      tvNum = n
    }
    mutation.mutate({
      title: cleanTitle,
      description: description.trim() || null,
      target_value: tvNum,
      target_unit: tvNum !== null ? targetUnit : null,
    })
  }

  if (!goal) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit goal</DialogTitle>
          <DialogDescription>
            Update title, description, and target. Type and links cannot be changed.
          </DialogDescription>
        </DialogHeader>

        <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Title</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Description</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Target value</span>
              <input
                type="number"
                min={1}
                value={targetValue}
                onChange={(e) => setTargetValue(e.target.value)}
                className="rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Target unit</span>
              <select
                value={targetUnit}
                onChange={(e) => setTargetUnit(e.target.value as TargetUnit)}
                className="rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              >
                {TARGET_UNITS.map((u) => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {error && (
            <div
              role="alert"
              className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-1.5 text-xs text-destructive"
            >
              {error}
            </div>
          )}

          <DialogFooter>
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {mutation.isPending ? "Saving..." : "Save changes"}
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
