// WeakAreasPanel -- per-section list of weak flashcard groups for a
// document. Clicking a section invokes the parent's filter callback
// (typically scrolls to / filters the FlashcardManager search).

import { useQuery } from "@tanstack/react-query"

import { API_BASE } from "@/lib/config"

import type { GapResult } from "./types"
import { fragileBarColor } from "./utils"

async function fetchGaps(documentId: string): Promise<GapResult[]> {
  const res = await fetch(`${API_BASE}/study/gaps/${documentId}`)
  if (!res.ok) return []
  return res.json() as Promise<GapResult[]>
}

interface WeakAreasPanelProps {
  documentId: string
  onSelectSection: (heading: string) => void
}

export function WeakAreasPanel({ documentId, onSelectSection }: WeakAreasPanelProps) {
  const { data: gaps = [], isLoading } = useQuery<GapResult[]>({
    queryKey: ["gaps", documentId],
    queryFn: () => fetchGaps(documentId),
    staleTime: 30_000,
  })

  if (isLoading) return null
  if (gaps.length === 0) return null

  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-base font-semibold text-foreground">Weak Areas</h3>
      <div className="flex flex-col gap-2">
        {gaps.map((gap, i) => {
          const pct = Math.min(100, Math.round((gap.avg_stability / 10) * 100))
          const heading = gap.section_heading ?? "Unsectioned"
          return (
            <button
              key={i}
              onClick={() => {
                if (gap.section_heading) onSelectSection(gap.section_heading)
              }}
              className="flex flex-col gap-1.5 rounded-lg border border-border bg-muted/20 p-3 text-left hover:bg-muted/40 transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="flex-1 text-sm font-medium text-foreground">{heading}</span>
                <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                  {gap.weak_card_count} weak
                </span>
              </div>
              {/* Fragility bar */}
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
                <div
                  className={`h-full rounded-full transition-all ${fragileBarColor(gap.avg_stability)}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-xs text-muted-foreground">
                avg stability: {gap.avg_stability.toFixed(2)}
              </span>
            </button>
          )
        })}
      </div>
    </section>
  )
}
