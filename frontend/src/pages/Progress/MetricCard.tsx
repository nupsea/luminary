import { Info } from "lucide-react"
import { useState } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import type { components } from "@/types/api"

import { formatMetric } from "./formatMetric"

type Metric = components["schemas"]["Metric"]

const ACCENTS: Record<string, { ring: string; iconBg: string; iconText: string }> = {
  primary: { ring: "ring-primary/10", iconBg: "bg-primary/10", iconText: "text-primary" },
  emerald: {
    ring: "ring-emerald-500/10",
    iconBg: "bg-emerald-500/10",
    iconText: "text-emerald-600",
  },
  amber: { ring: "ring-amber-500/10", iconBg: "bg-amber-500/10", iconText: "text-amber-600" },
  rose: { ring: "ring-rose-500/10", iconBg: "bg-rose-500/10", iconText: "text-rose-600" },
}

/**
 * One measured number, carrying how it was measured.
 *
 * Every metric here arrives from `/progress/summary` with its own definition,
 * basis and sample size, and the card shows all three on request. A number a
 * reader cannot account for is the failure this page had: it reported 90%
 * mastery after a single session, from an endpoint that was never a
 * learner-facing measurement.
 *
 * A metric that could not be computed shows an em dash and says why in the
 * basis, rather than a zero that reads as a measurement.
 */
export function MetricCard({
  label,
  metric,
  icon: Icon,
  loading,
  accent = "primary",
}: {
  label: string
  metric: Metric | undefined
  icon: React.ComponentType<{ size?: number; className?: string }>
  loading: boolean
  accent?: keyof typeof ACCENTS
}) {
  const [open, setOpen] = useState(false)
  const a = ACCENTS[accent] ?? ACCENTS.primary
  const absent = !loading && (!metric || metric.value === null)

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-2xl border border-border/50 bg-card/60 px-5 py-4 shadow-lg ring-1 backdrop-blur-xl transition-all duration-200 hover:shadow-xl",
        a.ring,
      )}
    >
      <div className="flex items-center gap-3">
        <div className={cn("flex h-9 w-9 items-center justify-center rounded-xl", a.iconBg)}>
          <Icon size={18} className={a.iconText} />
        </div>
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        {metric && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-label={`How ${label} is measured`}
            className="ml-auto text-muted-foreground/60 transition-colors hover:text-foreground"
          >
            <Info size={14} />
          </button>
        )}
      </div>

      {loading ? (
        <Skeleton className="h-8 w-20" />
      ) : (
        <span
          className={cn(
            "text-3xl font-extrabold tracking-tight",
            absent ? "text-muted-foreground/50" : "text-foreground",
          )}
        >
          {formatMetric(metric)}
        </span>
      )}

      {open && metric && (
        <div className="flex flex-col gap-1.5 border-t border-border/50 pt-2 text-xs leading-relaxed text-muted-foreground">
          <p>{metric.definition}</p>
          <p className="text-foreground/70">{metric.basis}</p>
        </div>
      )}
    </div>
  )
}
