// Inline rubric feedback shown both in TeachbackPanel (per-card after submit)
// and inside ExpandableResultRow on the results panel.

import { AlertTriangle, Check, X as XIcon } from "lucide-react"

import { type TeachbackResultItem, scoreBadgeClass } from "@/lib/studyApi"

export function InlineTeachbackFeedback({ result }: { result: TeachbackResultItem }) {
  const score = result.score ?? 0
  const passed = score >= 60
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        <span className={`rounded-full px-3 py-0.5 text-xs font-bold ${scoreBadgeClass(score)}`}>
          {score}/100
        </span>
        <span className={`text-sm font-medium ${passed ? "text-green-700 dark:text-green-400" : "text-amber-700 dark:text-amber-400"}`}>
          {passed ? "Good explanation!" : "Needs improvement"}
        </span>
      </div>

      {result.rubric && (
        <div className="flex flex-col gap-1 rounded-md bg-muted/40 p-2 text-xs">
          <div><span className="font-semibold">Clarity:</span> {result.rubric.clarity.evidence}</div>
        </div>
      )}

      {result.correct_points.length > 0 && (
        <div className="flex flex-col gap-0.5">
          <p className="text-xs font-semibold text-green-700 dark:text-green-400">Correct</p>
          {result.correct_points.map((p, i) => (
            <div key={i} className="flex items-start gap-1.5 text-xs text-foreground">
              <Check size={12} className="mt-0.5 shrink-0 text-green-600" />
              {p}
            </div>
          ))}
        </div>
      )}

      {result.missing_points.length > 0 && (
        <div className="flex flex-col gap-0.5">
          <p className="text-xs font-semibold text-amber-700 dark:text-amber-400">Missing</p>
          {result.missing_points.map((p, i) => (
            <div key={i} className="flex items-start gap-1.5 text-xs text-foreground">
              <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber-500" />
              {p}
            </div>
          ))}
        </div>
      )}

      {result.misconceptions.length > 0 && (
        <div className="flex flex-col gap-0.5">
          <p className="text-xs font-semibold text-red-700 dark:text-red-400">Misconceptions</p>
          {result.misconceptions.map((p, i) => (
            <div key={i} className="flex items-start gap-1.5 text-xs text-foreground">
              <XIcon size={12} className="mt-0.5 shrink-0 text-red-500" />
              {p}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
