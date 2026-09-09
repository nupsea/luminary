// One expandable row inside the session summary. Click toggles the detail
// panel, which shows the reference answer beside the verdict.
//
// The two used to be a flip: an "Answer/Evaluation" pill replaced one with the
// other. A learner deciding whether a score is fair is comparing what they said
// against what the card says, and that comparison cannot be made one at a time
// from memory. The grader is given this answer for reference; so is the reader.

import { ChevronDown, ChevronUp } from "lucide-react"

import { type TeachbackResultItem, scoreBadgeClass } from "@/lib/studyApi"

import { InlineTeachbackFeedback } from "./InlineTeachbackFeedback"

interface ExpandableResultRowProps {
  result: TeachbackResultItem
  fallbackQuestion: string
  isExpanded: boolean
  onToggle: () => void
}

export function ExpandableResultRow({
  result,
  fallbackQuestion,
  isExpanded,
  onToggle,
}: ExpandableResultRowProps) {
  const expected = result.expected_answer?.trim()

  return (
    <div
      data-testid="result-row"
      className="rounded-lg border border-border bg-card p-4 cursor-pointer transition-colors hover:bg-accent/30"
      onClick={onToggle}
    >
      <div className="flex items-center justify-between">
        <p className="flex-1 text-sm font-medium text-foreground">
          {result.question || fallbackQuestion}
        </p>
        <div className="flex items-center gap-2">
          <span
            className={`rounded-full px-3 py-0.5 text-xs font-bold ${scoreBadgeClass(result.score ?? 0)}`}
          >
            {result.score}/100
          </span>
          {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </div>
      </div>

      {isExpanded && (
        <div
          className="mt-3 border-t border-border pt-3"
          onClick={(e) => e.stopPropagation()}
        >
          {result.user_explanation && (
            <div className="mb-3">
              <p className="text-xs font-medium text-muted-foreground">Your explanation:</p>
              <blockquote className="mt-1 border-l-2 border-border pl-3 text-xs text-foreground/80 italic">
                {result.user_explanation}
              </blockquote>
            </div>
          )}

          <div
            data-testid="expected-answer"
            className="mb-3 rounded-md border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-900/40 dark:bg-emerald-950/20"
          >
            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
              What the card says
            </div>
            <p className="whitespace-pre-wrap text-xs text-foreground">
              {expected || "No reference answer available for this card."}
            </p>
          </div>

          <InlineTeachbackFeedback result={result} />
        </div>
      )}
    </div>
  )
}
