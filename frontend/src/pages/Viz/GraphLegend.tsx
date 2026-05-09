// Bottom-left legend on the Viz canvas. Two modes:
//   - retention overlay enabled: 5 mastery-strength swatches
//   - otherwise: top-8 entity types from graphStats.typeCounts
// Hidden when there is no graph to legend for.

import { BLIND_SPOT_COLOR, DEFAULT_COLOR, TYPE_COLORS } from "./constants"
import type { EntityType } from "@/lib/vizUtils"

interface GraphLegendProps {
  showRetention: boolean
  hasGraph: boolean
  typeCounts: Map<string, number> | null
}

export function GraphLegend({ showRetention, hasGraph, typeCounts }: GraphLegendProps) {
  if (showRetention && hasGraph) {
    return (
      <div className="absolute bottom-4 left-4 z-10 rounded-xl border border-border bg-background/90 backdrop-blur-sm shadow-sm px-3 py-2.5 max-w-[240px]">
        <p className="text-[9px] font-bold text-muted-foreground/60 uppercase tracking-widest mb-2">
          Retention Strength
        </p>
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {(
            [
              ["#ef4444", "Critical (<15%)"],
              ["#f97316", "Weak (15-40%)"],
              ["#84cc16", "Good (40-70%)"],
              ["#22c55e", "Strong (>70%)"],
              [BLIND_SPOT_COLOR, "No flashcards"],
            ] as const
          ).map(([color, label]) => (
            <div key={label} className="flex items-center gap-1">
              <span
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: color }}
              />
              <span className="text-[10px] text-muted-foreground">{label}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (!typeCounts || typeCounts.size === 0) return null

  return (
    <div className="absolute bottom-4 left-4 z-10 rounded-xl border border-border bg-background/90 backdrop-blur-sm shadow-sm px-3 py-2.5 max-w-[200px]">
      <p className="text-[9px] font-bold text-muted-foreground/60 uppercase tracking-widest mb-2">
        Legend
      </p>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {Array.from(typeCounts.entries())
          .filter(([t]) => t !== "cluster" && t !== "note")
          .sort((a, b) => b[1] - a[1])
          .slice(0, 8)
          .map(([type, count]) => (
            <div key={type} className="flex items-center gap-1">
              <span
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: TYPE_COLORS[type as EntityType] ?? DEFAULT_COLOR }}
              />
              <span className="text-[10px] text-muted-foreground">
                {type.toLowerCase().replace(/_/g, " ")} ({count})
              </span>
            </div>
          ))}
      </div>
    </div>
  )
}
