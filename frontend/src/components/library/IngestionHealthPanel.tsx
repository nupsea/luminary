import { useQuery } from "@tanstack/react-query"
import { Skeleton } from "@/components/ui/skeleton"

import { apiGet } from "@/lib/apiClient"

interface DiagnosticsResponse {
  chunk_count: number
  fts_count: number
  entity_count: number
  edge_count: number
  vector_count: number
}

const fetchDiagnostics = (documentId: string): Promise<DiagnosticsResponse> =>
  apiGet<DiagnosticsResponse>(`/documents/${documentId}/diagnostics`)

interface IngestionHealthPanelProps {
  documentId: string
  stage: string
}

interface MetricCardProps {
  label: string
  value: number
}

function MetricCard({ label, value }: MetricCardProps) {
  return (
    <div className="rounded-md border border-border bg-background p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-xl font-semibold text-foreground">{value}</p>
    </div>
  )
}

function healthBadge(data: DiagnosticsResponse): React.ReactElement {
  const counts = [
    data.chunk_count,
    data.fts_count,
    data.vector_count,
    data.entity_count,
    data.edge_count,
  ]
  const allZero = counts.every((c) => c === 0)
  const anyZero = counts.some((c) => c === 0)

  if (allZero) {
    return (
      <span className="inline-flex items-center rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-700">
        Empty — ingestion may have failed
      </span>
    )
  }
  if (anyZero) {
    return (
      <span className="inline-flex items-center rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-700">
        Partial
      </span>
    )
  }
  return (
    <span className="inline-flex items-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-700">
      Healthy
    </span>
  )
}

export function IngestionHealthPanel({ documentId, stage }: IngestionHealthPanelProps) {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["diagnostics", documentId],
    queryFn: () => fetchDiagnostics(documentId),
    // staleTime=0 means always re-fetch on mount so counts reflect latest state.
    staleTime: 0,
    // Only fetch when ingestion is complete.
    enabled: stage === "complete",
  })

  if (stage !== "complete") {
    return (
      <div className="text-xs text-muted-foreground">Ingestion in progress...</div>
    )
  }

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="flex items-center gap-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        <span>Could not load ingestion health</span>
        <button
          onClick={() => void refetch()}
          className="ml-auto shrink-0 rounded border border-amber-400 px-2 py-0.5 text-xs font-medium hover:bg-amber-100"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <MetricCard label="Chunks" value={data.chunk_count} />
        <MetricCard label="Keyword Index" value={data.fts_count} />
        <MetricCard label="Vectors" value={data.vector_count} />
        <MetricCard label="Entities" value={data.entity_count} />
        <MetricCard label="Co-occurrences" value={data.edge_count} />
      </div>
      <div>{healthBadge(data)}</div>
    </div>
  )
}
