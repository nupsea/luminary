import { useQuery } from "@tanstack/react-query"

import { Skeleton } from "@/components/ui/skeleton"
import { API_BASE } from "@/lib/config"

interface LearningObjective {
  id: string
  section_id: string
  text: string
  covered: boolean
}

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
  const { data, isLoading, isError } = useQuery({
    queryKey: ["objectives", documentId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/documents/${documentId}/objectives`)
      if (!res.ok) throw new Error("Failed to fetch objectives")
      return res.json() as Promise<{ objectives: LearningObjective[] }>
    },
    staleTime: 300_000,
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
              readOnly
              className="mt-0.5 shrink-0 accent-primary"
            />
            <span className="flex-1">{obj.text}</span>
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
