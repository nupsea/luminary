import { useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"
import { stripMarkdown } from "@/lib/utils"
import type { GoldenQuestion } from "./types"

interface QuestionListProps {
  questions: GoldenQuestion[]
}

export function QuestionList({ questions }: QuestionListProps) {
  const [openIds, setOpenIds] = useState<Set<string>>(new Set())

  if (questions.length === 0) {
    return <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">No questions.</div>
  }

  return (
    <div className="divide-y rounded-md border">
      {questions.map((question) => {
        const open = openIds.has(question.id)
        return (
          <button
            key={question.id}
            type="button"
            className="block w-full px-3 py-2 text-left hover:bg-accent/60"
            onClick={() => {
              const next = new Set(openIds)
              if (open) next.delete(question.id)
              else next.add(question.id)
              setOpenIds(next)
            }}
          >
            <div className="flex items-start gap-2">
              {open ? (
                <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
              ) : (
                <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
              )}
              <div className="min-w-0 flex-1">
                <div className="line-clamp-2 text-sm font-medium">
                  {stripMarkdown(question.question)}
                </div>
                {open && (
                  <div className="mt-2 space-y-2 text-xs text-muted-foreground">
                    <div>
                      <span className="font-medium text-foreground">Answer: </span>
                      {stripMarkdown(question.ground_truth_answer)}
                    </div>
                    <div>
                      <span className="font-medium text-foreground">Hint: </span>
                      {stripMarkdown(question.context_hint)}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </button>
        )
      })}
    </div>
  )
}
