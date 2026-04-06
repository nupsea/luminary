import { CheckCircle2, Loader2, StickyNote, XCircle } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router-dom"

import { API_BASE } from "@/lib/config"

export interface GapCardData {
  type: "gap_result"
  error?: string
  gaps: string[]
  covered: string[]
  query_used?: string
  document_id?: string
  auto_collection_id?: string
}

interface GapResultCardProps {
  data: GapCardData
  documentId?: string
}

type ButtonState = "idle" | "loading" | "done" | "error"

export function GapResultCard({ data, documentId }: GapResultCardProps) {
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

  const effectiveDocId = data.document_id ?? documentId ?? ""

  async function handleGenerateFlashcards() {
    setBtnState("loading")
    setErrorMsg("")
    try {
      const res = await fetch(`${API_BASE}/flashcards/from-gaps`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gaps: data.gaps, document_id: effectiveDocId }),
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
                <span className="flex-1">{gap}</span>
                <button
                  onClick={() => {
                    window.dispatchEvent(
                      new CustomEvent("luminary:navigate", {
                        detail: {
                          tab: "notes",
                          prefilledContent: `# ${gap}`,
                          collectionId: data.auto_collection_id ?? undefined,
                        },
                      })
                    )
                  }}
                  className="ml-1 shrink-0 flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                  title="Take a note on this"
                >
                  <StickyNote size={12} />
                  Note
                </button>
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

      {btnState === "done" ? (
        <div className="flex items-center gap-2 text-sm text-green-700">
          <CheckCircle2 size={14} className="shrink-0 text-green-500" />
          <span>{createdCount} flashcard{createdCount !== 1 ? "s" : ""} added to your deck.</span>
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
            onClick={handleGenerateFlashcards}
            className={`mt-1 flex w-fit items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs ${
              !hasGaps
                ? "cursor-not-allowed border-border bg-muted text-muted-foreground opacity-50"
                : btnState === "loading"
                  ? "cursor-not-allowed border-border bg-muted text-muted-foreground"
                  : "border-border bg-background text-foreground hover:bg-muted"
            }`}
          >
            {btnState === "loading" && <Loader2 size={12} className="animate-spin" />}
            {btnState === "loading" ? "Generating..." : btnState === "error" ? "Retry" : "Generate Flashcards for these Gaps"}
          </button>
        </>
      )}
    </div>
  )
}
