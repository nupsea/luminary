import { CheckCircle2, Loader2, XCircle, AlertTriangle } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router-dom"

import { API_BASE } from "@/lib/config"
import { RubricCard, type Rubric } from "@/components/RubricCard"

export interface TeachBackCardData {
  type: "teach_back_result"
  correct: string[]
  misconceptions: string[]
  gaps: string[]
  encouragement: string
  document_id: string
  error?: string
  error_detail?: string
  rubric?: Rubric | null  // S156: structured rubric; null for legacy rows
}

interface TeachBackResultCardProps {
  data: TeachBackCardData
}

type ButtonState = "idle" | "loading" | "done" | "error"

export function TeachBackResultCard({ data }: TeachBackResultCardProps) {
  const [btnState, setBtnState] = useState<ButtonState>("idle")
  const [createdCount, setCreatedCount] = useState(0)
  const [errorMsg, setErrorMsg] = useState("")

  if (data.error) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
        {data.error}
      </div>
    )
  }

  const hasCorrect = data.correct.length > 0
  const hasMisconceptions = data.misconceptions.length > 0
  const hasGaps = data.gaps.length > 0
  const allEmpty = !hasCorrect && !hasMisconceptions && !hasGaps

  async function handleAddGaps() {
    setBtnState("loading")
    setErrorMsg("")
    try {
      const res = await fetch(`${API_BASE}/flashcards/from-gaps`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gaps: data.gaps, document_id: data.document_id }),
      })
      if (res.status === 503) {
        setErrorMsg("Ollama is unavailable. Start it with: ollama serve")
        setBtnState("error")
        return
      }
      if (!res.ok) {
        const detail = ((await res.json()) as { detail?: string }).detail ?? `HTTP ${res.status}`
        setErrorMsg(detail)
        setBtnState("error")
        return
      }
      const body = (await res.json()) as { created: number }
      setCreatedCount(body.created)
      setBtnState("done")
    } catch {
      setErrorMsg("Request failed. Please try again.")
      setBtnState("error")
    }
  }

  // S156: if rubric is present, render RubricCard (primary path)
  if (data.rubric) {
    return (
      <div className="flex flex-col gap-3">
        {data.encouragement && (
          <p className="text-sm italic text-muted-foreground">{data.encouragement}</p>
        )}
        <RubricCard rubric={data.rubric} documentId={data.document_id} />
      </div>
    )
  }

  // Legacy rendering path (rubric is null/undefined)
  return (
    <div className="flex flex-col gap-3">
      {data.encouragement && (
        <p className="text-sm italic text-muted-foreground">{data.encouragement}</p>
      )}

      {allEmpty && (
        <div className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
          Excellent explanation! Nothing to correct.
        </div>
      )}

      {hasCorrect && (
        <div>
          <p className="mb-1 text-xs font-medium text-green-600">What you got right</p>
          <ul className="flex flex-col gap-1">
            {data.correct.map((item, i) => (
              <li key={i} className="flex items-start gap-1.5 text-sm">
                <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-green-500" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {hasMisconceptions && (
        <div>
          <p className="mb-1 text-xs font-medium text-red-600">Misconceptions to correct</p>
          <ul className="flex flex-col gap-1">
            {data.misconceptions.map((item, i) => (
              <li key={i} className="flex items-start gap-1.5 text-sm">
                <XCircle size={14} className="mt-0.5 shrink-0 text-red-500" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {hasGaps && (
        <div>
          <p className="mb-1 text-xs font-medium text-amber-600">Gaps to fill</p>
          <ul className="flex flex-col gap-1">
            {data.gaps.map((item, i) => (
              <li key={i} className="flex items-start gap-1.5 text-sm">
                <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-500" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {btnState === "done" ? (
        <div className="flex items-center gap-2 text-sm text-green-700">
          <CheckCircle2 size={14} className="shrink-0 text-green-500" />
          <span>
            {createdCount} flashcard{createdCount !== 1 ? "s" : ""} added to your deck.
          </span>
          <Link to="/study" className="ml-1 underline text-blue-600 hover:text-blue-800">
            Go to Study
          </Link>
        </div>
      ) : (
        <>
          {btnState === "error" && (
            <p className="text-xs text-red-600">{errorMsg}</p>
          )}
          <button
            disabled={!hasGaps || btnState === "loading"}
            onClick={handleAddGaps}
            className={`mt-1 flex w-fit items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs ${
              !hasGaps
                ? "cursor-not-allowed border-border bg-muted text-muted-foreground opacity-50"
                : btnState === "loading"
                  ? "cursor-not-allowed border-border bg-muted text-muted-foreground"
                  : "border-border bg-background text-foreground hover:bg-muted"
            }`}
          >
            {btnState === "loading" && <Loader2 size={12} className="animate-spin" />}
            {btnState === "loading"
              ? "Adding..."
              : btnState === "error"
                ? "Retry"
                : "Add Gaps to My Flashcards"}
          </button>
        </>
      )}
    </div>
  )
}
