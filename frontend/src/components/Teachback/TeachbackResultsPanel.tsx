// Session-summary results list: one row per pending/error/complete teach-back,
// with an aggregate score header when all evaluations have landed.

import { Loader2 } from "lucide-react"
import { useState } from "react"

import { type PendingTeachback, type TeachbackResultItem } from "@/lib/studyApi"

import { ExpandableResultRow } from "./ExpandableResultRow"
import type { TeachbackStats } from "./useTeachbackPolling"

interface TeachbackResultsPanelProps {
  pending: PendingTeachback[]
  stats: TeachbackStats
  results: TeachbackResultItem[] | undefined
}

export function TeachbackResultsPanel({
  pending,
  stats,
  results,
}: TeachbackResultsPanelProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  return (
    <div className="flex w-full max-w-2xl flex-col gap-4">
      {/* Summary bar */}
      {stats.allDone && stats.completedCount > 0 && (
        <div className="rounded-lg border border-border bg-card/50 p-4 text-center">
          <span className="text-sm text-muted-foreground">Average score: </span>
          <span
            className={`text-2xl font-bold ${
              stats.avgScore >= 80
                ? "text-green-600"
                : stats.avgScore >= 60
                  ? "text-amber-600"
                  : "text-red-600"
            }`}
          >
            {stats.avgScore}/100
          </span>
          <span className="ml-3 text-sm text-muted-foreground">
            ({stats.passCount}/{stats.completedCount} passed)
          </span>
        </div>
      )}

      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-foreground">Results</h3>
        {!stats.allDone && (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 size={12} className="animate-spin" />
            Evaluating...
          </span>
        )}
      </div>

      {pending.map((tb) => {
        if (tb.id.startsWith("error-")) {
          return (
            <div key={tb.id} className="rounded-lg border border-border bg-muted/30 p-4">
              <p className="text-sm font-medium text-foreground">{tb.question}</p>
              <p className="mt-2 text-xs text-amber-700">
                Submission failed. Check if Ollama is running.
              </p>
            </div>
          )
        }

        if (tb.id.startsWith("temp-")) {
          return (
            <div key={tb.id} className="rounded-lg border border-border bg-muted/30 p-4">
              <p className="text-sm font-medium text-foreground">{tb.question}</p>
              <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 size={12} className="animate-spin" />
                Submitting...
              </div>
            </div>
          )
        }

        const result = results?.find((r) => r.id === tb.id)

        if (!result || result.status === "pending") {
          return (
            <div key={tb.id} className="rounded-lg border border-border bg-muted/30 p-4">
              <p className="text-sm font-medium text-foreground">{tb.question}</p>
              <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 size={12} className="animate-spin" />
                Evaluating...
              </div>
            </div>
          )
        }

        if (result.status === "error") {
          return (
            <div key={tb.id} className="rounded-lg border border-border bg-muted/30 p-4">
              <p className="text-sm font-medium text-foreground">{tb.question}</p>
              <p className="mt-2 text-xs text-amber-700">Evaluation failed.</p>
            </div>
          )
        }

        const isExpanded = expandedId === tb.id
        return (
          <ExpandableResultRow
            key={tb.id}
            result={result}
            fallbackQuestion={tb.question}
            isExpanded={isExpanded}
            onToggle={() => setExpandedId(isExpanded ? null : tb.id)}
          />
        )
      })}
    </div>
  )
}
