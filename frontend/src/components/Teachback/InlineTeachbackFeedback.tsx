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

      {/* Why the score is what it is. Only clarity's evidence used to be shown,
          so the two dimensions that actually move the score -- accuracy and
          completeness -- were fetched, stored and then dropped on the floor. */}
      {result.rubric ? (
        <div className="flex flex-col gap-2 rounded-md bg-muted/40 p-3 text-xs">
          <p className="font-semibold uppercase tracking-wider text-muted-foreground/70">
            Why this score
          </p>
          <Dimension
            label="Accuracy"
            score={result.rubric.accuracy.score}
            body={result.rubric.accuracy.evidence}
          />
          <Dimension
            label="Completeness"
            score={result.rubric.completeness.score}
            body={
              result.rubric.completeness.missed_points.length > 0
                ? `Missed: ${result.rubric.completeness.missed_points.join("; ")}`
                : "Nothing material was left out."
            }
          />
          <Dimension
            label="Clarity"
            score={result.rubric.clarity.score}
            body={result.rubric.clarity.evidence}
          />
        </div>
      ) : (
        // The rubric is a second, best-effort LLM call (study.py:1384). When it
        // fails the row is stored with a null rubric, and saying so beats an
        // absence the reader reads as "no notes".
        <p className="rounded-md bg-muted/40 p-3 text-xs text-muted-foreground">
          No breakdown came back for this attempt -- the score above stands on its own.
        </p>
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

function Dimension({ label, score, body }: { label: string; score: number; body: string }) {
  return (
    <div className="flex gap-2">
      {/* 0-100 per dimension, the scale _RUBRIC_USER_TMPL asks the model for
          (study.py:284) -- not the 0-5 a rubric is usually assumed to use. */}
      <span className="w-28 shrink-0 font-semibold text-foreground">
        {label} {score}/100
      </span>
      <span className="flex-1 text-muted-foreground">{body}</span>
    </div>
  )
}
