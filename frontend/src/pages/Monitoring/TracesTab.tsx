// Traces tab: Phoenix link card + live span table. Spans auto-refresh
// every 15 s (silently -- stale data stays visible if a refresh fails)
// with a manual refresh button as well.

import { useState } from "react"

import { RefreshCw } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"

import { TracesCard } from "./Charts"
import {
  EmptyState,
  KindChip,
  SectionErrorCard,
  SectionSkeleton,
  StatusBadge,
  TraceDetailPanel,
} from "./SharedUI"
import { fetchPhoenixUrl, fetchTraces } from "./api"
import type { PhoenixUrl, TraceItem, TracesResponse } from "./types"
import { useSection } from "./useSection"
import { formatDuration } from "./utils"

export function TracesTab() {
  const phoenix = useSection<PhoenixUrl | null>("Phoenix URL", fetchPhoenixUrl, null, 30_000)
  const traces = useSection<TracesResponse>("Recent Traces", fetchTraces, { traces: [] }, 15_000)
  const [selectedTrace, setSelectedTrace] = useState<TraceItem | null>(null)

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-2">
        {phoenix.loading ? (
          <Skeleton className="h-16 w-full rounded-lg" />
        ) : phoenix.error ? (
          <SectionErrorCard name="Phoenix status" />
        ) : (
          <TracesCard phoenix={phoenix.data} />
        )}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-foreground">Recent Spans</h2>
          <button
            onClick={() => traces.reload()}
            title="Refresh now (auto-refreshes every 15 s)"
            className="flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <RefreshCw size={12} />
            Refresh
          </button>
        </div>
        {traces.loading ? (
          <SectionSkeleton rows={5} />
        ) : traces.error ? (
          <SectionErrorCard name="Recent Spans" />
        ) : (
          <>
            {traces.data.message && (
              <p className="text-sm text-muted-foreground">{traces.data.message}</p>
            )}
            {traces.data.traces.length === 0 ? (
              <EmptyState message="No spans yet. Ask a question or ingest a document to generate traces." />
            ) : (
              <div className="overflow-auto rounded-lg border border-border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-secondary/50">
                      <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Time</th>
                      <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Operation</th>
                      <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Kind</th>
                      <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">Duration</th>
                      <th className="px-4 py-2 text-center text-xs font-semibold text-muted-foreground">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {traces.data.traces.map((t) => (
                      <tr
                        key={t.span_id || `${t.trace_id}-${t.start_time}`}
                        onClick={() => setSelectedTrace(t)}
                        className="cursor-pointer border-b border-border last:border-0 hover:bg-accent"
                      >
                        <td
                          className="whitespace-nowrap px-4 py-2 text-xs text-muted-foreground"
                          title={t.start_time ? new Date(t.start_time).toLocaleString() : undefined}
                        >
                          {t.start_time ? new Date(t.start_time).toLocaleTimeString() : "—"}
                        </td>
                        <td className="px-4 py-2 font-medium text-foreground">
                          <span className={t.parent_id ? "pl-4 text-muted-foreground" : ""}>
                            {t.operation_name}
                          </span>
                        </td>
                        <td className="px-4 py-2">
                          <KindChip kind={t.span_kind ?? "UNKNOWN"} />
                        </td>
                        <td className="whitespace-nowrap px-4 py-2 text-right text-muted-foreground">
                          {formatDuration(t.duration_ms)}
                        </td>
                        <td className="px-4 py-2 text-center">
                          <StatusBadge status={t.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>

      {selectedTrace && (
        <TraceDetailPanel
          trace={selectedTrace}
          phoenixUrl={phoenix.data?.enabled ? phoenix.data.url : undefined}
          onClose={() => setSelectedTrace(null)}
        />
      )}
    </div>
  )
}
