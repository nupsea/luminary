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

export function EnrichmentStatusPill() {
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

  return (
    <div
      className="pointer-events-auto flex items-center gap-3 rounded-xl border border-border bg-background/95 px-4 py-3 shadow-lg backdrop-blur-md"
      style={{ minWidth: 320, maxWidth: 420 }}
      role="status"
      aria-live="polite"
    >
      <Sparkles className="h-5 w-5 shrink-0 animate-pulse text-primary" aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate text-sm font-semibold text-foreground">
          Enriching {docs} {docs === 1 ? "document" : "documents"}
        </span>
        <span className="text-xs text-muted-foreground">
          {remaining} {remaining === 1 ? "task" : "tasks"} left &middot; figures and diagrams
          are read by a local model
        </span>
      </div>
    </div>
  )
}
