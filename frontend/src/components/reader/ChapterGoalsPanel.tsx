import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { Skeleton } from "@/components/ui/skeleton"
import { apiGet, apiPatch } from "@/lib/apiClient"

interface LearningObjective {
  id: string
  section_id: string
  text: string
  covered: boolean
}

const patchObjectiveCovered = (
  documentId: string,
  objectiveId: string,
  covered: boolean,
): Promise<LearningObjective> =>
  apiPatch<LearningObjective>(
    `/documents/${documentId}/objectives/${objectiveId}`,
    { covered },
  )

interface ChapterProgressRingProps {
  pct: number
  size?: number
}

export function ChapterProgressRing({ pct, size = 12 }: ChapterProgressRingProps) {
  const r = (size - 2) / 2
  const circ = 2 * Math.PI * r
  const dashOffset = circ - (pct / 100) * circ
  return (
    <svg width={size} height={size} className="shrink-0" aria-label={`${Math.round(pct)}% covered`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={1.5} className="text-muted/30" />
      <circle
        cx={size / 2} cy={size / 2} r={r}
        fill="none" stroke="currentColor" strokeWidth={1.5}
        strokeDasharray={circ} strokeDashoffset={dashOffset}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        className="text-primary"
      />
    </svg>
  )
}

interface ChapterGoalsPanelProps {
  documentId: string
  sectionId?: string | null
  onStudyClick: (sectionId: string) => void
}

export function ChapterGoalsPanel({ documentId, sectionId, onStudyClick }: ChapterGoalsPanelProps) {
  const qc = useQueryClient()
  const { data, isLoading, isError } = useQuery({
    queryKey: ["objectives", documentId],
    queryFn: () =>
      apiGet<{ objectives: LearningObjective[] }>(
        `/documents/${documentId}/objectives`,
      ),
    staleTime: 300_000,
  })

  // Manual toggle (B) -- independent of the auto-tracker. Optimistic so
  // the checkbox feels instant; on error we roll back and toast.
  const toggleMutation = useMutation({
    mutationFn: ({ id, covered }: { id: string; covered: boolean }) =>
      patchObjectiveCovered(documentId, id, covered),
    onMutate: async ({ id, covered }) => {
      await qc.cancelQueries({ queryKey: ["objectives", documentId] })
      const prev = qc.getQueryData<{ objectives: LearningObjective[] }>([
        "objectives",
        documentId,
      ])
      if (prev) {
        qc.setQueryData(["objectives", documentId], {
          ...prev,
          objectives: prev.objectives.map((o) => (o.id === id ? { ...o, covered } : o)),
        })
      }
      return { prev }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(["objectives", documentId], ctx.prev)
      toast.error("Could not update goal")
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["objectives", documentId] })
      // Progress ring on the section list reads from /progress, which
      // counts covered objectives -- keep it in sync.
      qc.invalidateQueries({ queryKey: ["document-progress", documentId] })
    },
  })

  if (isLoading) {
    return (
      <div className="mb-4 flex flex-col gap-1.5 py-2">
        {[1, 2, 3].map((i) => <Skeleton key={i} className="h-4 w-full" />)}
      </div>
    )
  }

  if (isError) {
    return <p className="mb-4 text-xs text-destructive">Could not load chapter goals.</p>
  }

  if (!data || data.objectives.length === 0) {
    return null
  }

  const visibleObjectives = sectionId
    ? data.objectives.filter((o) => o.section_id === sectionId)
    : data.objectives

  if (visibleObjectives.length === 0) {
    return (
      <div className="mb-4 rounded-lg border border-border bg-card p-4">
        <h3 className="mb-1 text-sm font-semibold text-foreground">Chapter Goals</h3>
        <p className="text-xs text-muted-foreground">No learning objectives for this section.</p>
      </div>
    )
  }

  return (
    <div className="mb-4 rounded-lg border border-border bg-card p-4">
      <h3 className="mb-2 text-sm font-semibold text-foreground">Chapter Goals</h3>
      <ul className="space-y-1.5">
        {visibleObjectives.map((obj) => (
          <li key={obj.id} className="flex items-start gap-2 text-xs text-foreground/80">
            <input
              type="checkbox"
              checked={obj.covered}
              disabled={toggleMutation.isPending}
              onChange={(e) =>
                toggleMutation.mutate({ id: obj.id, covered: e.target.checked })
              }
              title={
                obj.covered
                  ? "Marked covered. Uncheck to revert."
                  : "Mark this goal covered manually."
              }
              className="mt-0.5 shrink-0 accent-primary cursor-pointer disabled:cursor-wait"
            />
            <span className={`flex-1 ${obj.covered ? "line-through text-muted-foreground" : ""}`}>
              {obj.text}
            </span>
            {!obj.covered && (
              <button
                onClick={() => onStudyClick(obj.section_id)}
                className="ml-auto shrink-0 rounded bg-primary px-2 py-0.5 text-xs text-primary-foreground hover:bg-primary/90"
              >
                Study
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
