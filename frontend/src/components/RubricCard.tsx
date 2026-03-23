/**
 * RubricCard -- shared 3-dimension rubric component for Feynman and Teach-back (S156).
 *
 * Three UI states:
 *   Loading: parent handles this -- RubricCard only renders when rubric is present
 *   Error/null: parent renders legacy UI when rubric is null (never mounts RubricCard)
 *   Empty completeness: "No missed points identified" when missed_points is empty
 */

import { useState } from "react"
import { CheckCircle2, Loader2 } from "lucide-react"
import { API_BASE } from "@/lib/config"

export interface RubricDimension {
  score: number
  evidence: string
}

export interface RubricCompleteness {
  score: number
  missed_points: string[]
}

export interface Rubric {
  accuracy: RubricDimension
  completeness: RubricCompleteness
  clarity: RubricDimension
}

interface RubricCardProps {
  rubric: Rubric
  documentId: string
}

function scoreBadgeClass(score: number): string {
  if (score >= 80) return "bg-green-100 text-green-700"
  if (score >= 50) return "bg-yellow-100 text-yellow-700"
  return "bg-red-100 text-red-700"
}

interface MissedPointRowProps {
  point: string
  documentId: string
}

type CreateState = "idle" | "loading" | "done" | "error"

function MissedPointRow({ point, documentId }: MissedPointRowProps) {
  const [state, setState] = useState<CreateState>("idle")
  const [errorMsg, setErrorMsg] = useState("")

  async function handleCreate() {
    setState("loading")
    setErrorMsg("")
    try {
      const res = await fetch(`${API_BASE}/flashcards/create-trace`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: `Explain: ${point}`,
          answer: "",
          source_excerpt: point,
          document_id: documentId,
        }),
      })
      if (!res.ok) {
        const detail = ((await res.json()) as { detail?: string }).detail ?? `HTTP ${res.status}`
        setErrorMsg(detail)
        setState("error")
        return
      }
      setState("done")
    } catch {
      setErrorMsg("Request failed. Please try again.")
      setState("error")
    }
  }

  return (
    <li className="flex items-start justify-between gap-2 py-0.5 text-sm">
      <span className="text-foreground">{point}</span>
      <span className="shrink-0">
        {state === "done" ? (
          <span className="flex items-center gap-1 text-xs text-green-600">
            <CheckCircle2 size={12} />
            Added
          </span>
        ) : state === "error" ? (
          <span className="flex flex-col items-end gap-0.5">
            <span className="text-xs text-red-600">{errorMsg}</span>
            <button
              onClick={() => void handleCreate()}
              className="text-xs text-blue-600 underline hover:text-blue-800"
            >
              Retry
            </button>
          </span>
        ) : (
          <button
            disabled={state === "loading"}
            onClick={() => void handleCreate()}
            className="flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-xs text-foreground hover:bg-muted disabled:opacity-50"
          >
            {state === "loading" && <Loader2 size={10} className="animate-spin" />}
            {state === "loading" ? "Adding..." : "Create flashcard"}
          </button>
        )}
      </span>
    </li>
  )
}

export function RubricCard({ rubric, documentId }: RubricCardProps) {
  return (
    <div className="flex flex-col gap-3 rounded-md border border-border bg-card p-3 text-sm">
      {/* Accuracy */}
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-foreground uppercase tracking-wide">Accuracy</span>
          <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${scoreBadgeClass(rubric.accuracy.score)}`}>
            {rubric.accuracy.score}/100
          </span>
        </div>
        {rubric.accuracy.evidence && (
          <p className="text-xs italic text-muted-foreground">{rubric.accuracy.evidence}</p>
        )}
      </div>

      {/* Completeness */}
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-foreground uppercase tracking-wide">Completeness</span>
          <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${scoreBadgeClass(rubric.completeness.score)}`}>
            {rubric.completeness.score}/100
          </span>
        </div>
        {rubric.completeness.missed_points.length === 0 ? (
          <p className="text-xs text-muted-foreground">No missed points identified.</p>
        ) : (
          <ul className="mt-0.5 flex flex-col divide-y divide-border">
            {rubric.completeness.missed_points.map((point, i) => (
              <MissedPointRow key={i} point={point} documentId={documentId} />
            ))}
          </ul>
        )}
      </div>

      {/* Clarity */}
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-foreground uppercase tracking-wide">Clarity</span>
          <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${scoreBadgeClass(rubric.clarity.score)}`}>
            {rubric.clarity.score}/100
          </span>
        </div>
        {rubric.clarity.evidence && (
          <p className="text-xs italic text-muted-foreground">{rubric.clarity.evidence}</p>
        )}
      </div>
    </div>
  )
}
