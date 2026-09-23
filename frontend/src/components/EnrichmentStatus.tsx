import { useQuery } from "@tanstack/react-query"
import { Sparkles } from "lucide-react"

import { apiGet } from "@/lib/apiClient"

export interface EnrichmentQueue {
  pending: number
  running: number
  skipped: number
  failed: number
  documents_active: number
  active: boolean
}

const ACTIVE_POLL_MS = 5_000
const IDLE_POLL_MS = 20_000

export function EnrichmentStatus() {
  const { data } = useQuery({
    queryKey: ["enrichment-queue"],
    queryFn: () => apiGet<EnrichmentQueue>("/enrichment/queue"),
    refetchInterval: (query) => (query.state.data?.active ? ACTIVE_POLL_MS : IDLE_POLL_MS),
  })

  // Ambient indicator: silent unless work is actually running. A fetch failure
  // must not put an error card in front of someone who never asked for this.
  if (!data?.active) return null

  const remaining = data.pending + data.running
  const docs = data.documents_active

  const label = `Enriching ${docs} ${docs === 1 ? "document" : "documents"}, ${remaining} ${remaining === 1 ? "task" : "tasks"} left`

  // In the nav rail: it runs for minutes, and floating over a page it covered
  // the PDF pager at the foot and page toolbars at the top.
  return (
    <div
      className="flex flex-col items-center gap-0.5"
      title={`${label}. Figures and diagrams are read by a local model.`}
      role="status"
      aria-live="polite"
    >
      <Sparkles className="h-4 w-4 animate-pulse text-primary" aria-hidden />
      <span className="text-[9px] font-medium tabular-nums text-sidebar-foreground/70" aria-hidden>
        {remaining}
      </span>
      <span className="sr-only">{label}</span>
    </div>
  )
}
