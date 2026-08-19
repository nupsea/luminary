// GroundingPanel -- how many of this deck's cards can prove where they came from.
//
// The review screen presents `source_excerpt` under a heading that reads "Source".
// Measured on a real 949-card library, 26% of the cards that quoted anything quoted
// text their document does not contain. This is the deck-level view of that, and
// the button that recomputes it.
//
// Four states, not a pass rate: "checked and found" and "nothing could be checked"
// are different answers, and averaging them into one number is what let an
// unaudited deck read clean.

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertCircle, ChevronDown, ChevronUp, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { apiGet, apiPost } from "@/lib/apiClient"

interface GroundingReport {
  scanned: number
  changed: number
  verified: number
  unsupported: number
  unverifiable: number
  unchecked: number
}

const STATES: { key: keyof GroundingReport; label: string; tone: string }[] = [
  {
    key: "verified",
    label: "quote found in the document",
    tone: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  },
  {
    key: "unsupported",
    label: "quote not in the document",
    tone: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  },
  {
    key: "unverifiable",
    label: "nothing to check against",
    tone: "bg-muted text-muted-foreground",
  },
  {
    key: "unchecked",
    label: "not checked yet",
    tone: "bg-muted text-muted-foreground",
  },
]

export function GroundingPanel({ documentId }: { documentId: string }) {
  const [isOpen, setIsOpen] = useState(false)
  const qc = useQueryClient()

  const { data, isLoading, isError, refetch } = useQuery<GroundingReport, Error>({
    queryKey: ["grounding", documentId],
    queryFn: () =>
      apiGet<GroundingReport>("/flashcards/grounding", { document_id: documentId }),
    staleTime: 60_000,
    enabled: isOpen,
  })

  const audit = useMutation({
    mutationFn: () =>
      apiPost<GroundingReport>("/flashcards/grounding/audit", {
        document_id: documentId,
      }),
    onSuccess: (report) => {
      qc.invalidateQueries({ queryKey: ["grounding", documentId] })
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      toast.success(
        report.unsupported > 0
          ? `${report.unsupported} of ${report.scanned} cards quote text this document does not contain`
          : `Checked ${report.scanned} cards`,
      )
    },
    onError: () => toast.error("Could not check card sources"),
  })

  return (
    <section className="flex flex-col gap-2 rounded-md border border-border bg-card p-4">
      <button
        className="flex items-center justify-between text-left"
        onClick={() => setIsOpen((v) => !v)}
      >
        <span className="text-base font-semibold text-foreground">Source grounding</span>
        {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {isOpen && (
        <div className="flex flex-col gap-3 pt-2">
          {isLoading && <div className="h-8 w-2/3 animate-pulse rounded bg-muted" />}

          {isError && (
            <div className="flex items-center gap-3 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
              <AlertCircle size={16} />
              <span>Could not load source grounding</span>
              <button
                onClick={() => refetch()}
                className="ml-auto rounded border border-red-400 px-2 py-0.5 text-xs hover:bg-red-100 dark:hover:bg-red-900"
              >
                Retry
              </button>
            </div>
          )}

          {!isLoading && !isError && data && (
            <>
              <div className="flex flex-wrap gap-2">
                {STATES.map(({ key, label, tone }) => (
                  <div
                    key={key}
                    className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${tone}`}
                  >
                    <span className="font-bold">{data[key]}</span>
                    <span>{label}</span>
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                A card quotes the passage it was written from. Checking looks for that
                quote in this document -- no model is involved, and nothing is deleted.
              </p>
              <button
                onClick={() => audit.mutate()}
                disabled={audit.isPending || data.scanned === 0}
                className="flex w-fit items-center gap-2 rounded border border-border px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50"
              >
                {audit.isPending && <Loader2 size={13} className="animate-spin" />}
                {audit.isPending ? "Checking..." : "Check sources"}
              </button>
            </>
          )}
        </div>
      )}
    </section>
  )
}
