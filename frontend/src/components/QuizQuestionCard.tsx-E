import { useState } from "react"
import { Badge } from "@/components/ui/badge"

interface QuizQuestionCardProps {
  question: string
  contextHint: string
  documentId: string
  error?: string
  onSubmit: (answer: string) => void
}

export function QuizQuestionCard({
  question,
  contextHint,
  error,
  onSubmit,
}: QuizQuestionCardProps) {
  const [answer, setAnswer] = useState("")
  const [submitted, setSubmitted] = useState(false)

  if (error) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
        {error}
      </div>
    )
  }

  function handleSubmit() {
    if (!answer.trim() || submitted) return
    setSubmitted(true)
    onSubmit(`My answer: ${answer.trim()}`)
  }

  return (
    <div className="border-l-4 border-blue-500 pl-3 flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Badge variant="blue" className="text-xs">
          Quiz
        </Badge>
      </div>
      <p className="text-sm font-semibold">{question}</p>
      {!submitted ? (
        <>
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="Type your answer..."
            rows={2}
            className="w-full resize-none rounded-md border border-border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            onKeyDown={(e) => {
              if (e.key === "Enter" && e.ctrlKey) {
                e.preventDefault()
                handleSubmit()
              }
            }}
          />
          <button
            onClick={handleSubmit}
            disabled={!answer.trim()}
            className="w-full rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Submit Answer
          </button>
        </>
      ) : (
        <div className="flex flex-col gap-1">
          <p className="text-xs text-muted-foreground">
            Answer submitted.
          </p>
          {contextHint && (
            <p className="text-xs text-slate-600 border-l-2 border-slate-300 pl-2">
              {contextHint}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
