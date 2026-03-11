import { CheckCircle2, XCircle } from "lucide-react"

export interface GapCardData {
  type: string
  error?: string
  gaps: string[]
  covered: string[]
  query_used?: string
}

interface GapResultCardProps {
  data: GapCardData
}

export function GapResultCard({ data }: GapResultCardProps) {
  if (data.error) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
        {data.error}
      </div>
    )
  }

  const hasGaps = data.gaps.length > 0
  const hasCovered = data.covered.length > 0
  const hasContent = hasGaps || hasCovered

  if (!hasContent) {
    return (
      <div className="text-sm text-muted-foreground">
        No analysis available. Ask about a document with linked notes.
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Gap Analysis
      </p>

      {!hasGaps && (
        <div className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
          No significant gaps detected -- your notes cover this material well.
        </div>
      )}

      {hasGaps && (
        <div>
          <p className="mb-1 text-xs font-medium text-red-600">Concepts you missed</p>
          <ul className="flex flex-col gap-1">
            {data.gaps.map((gap, i) => (
              <li key={i} className="flex items-start gap-1.5 text-sm">
                <XCircle size={14} className="mt-0.5 shrink-0 text-red-500" />
                <span>{gap}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {hasCovered && (
        <div>
          <p className="mb-1 text-xs font-medium text-green-600">Well covered</p>
          <ul className="flex flex-col gap-1">
            {data.covered.map((item, i) => (
              <li key={i} className="flex items-start gap-1.5 text-sm">
                <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-green-500" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <button
        disabled
        title="Coming in next update"
        className="mt-1 w-fit rounded-md border border-border bg-muted px-3 py-1.5 text-xs text-muted-foreground opacity-50 cursor-not-allowed"
      >
        Generate Flashcards for these Gaps
      </button>
    </div>
  )
}
