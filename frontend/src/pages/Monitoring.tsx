/**
 * Monitoring tab — traces table and system overview.
 *
 * Data sources:
 *   GET /monitoring/overview  — counts, Phoenix status, LLM status
 *   GET /monitoring/traces    — last 50 spans from Phoenix
 */

import { useEffect, useState } from "react"
import { Loader2, X as XIcon } from "lucide-react"

const API_BASE = "http://localhost:8000"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TraceItem {
  span_id: string
  trace_id: string
  operation_name: string
  start_time: string
  duration_ms: number
  status: string
  attributes: Record<string, unknown>
}

interface TracesResponse {
  traces: TraceItem[]
  message?: string | null
}

interface MonitoringOverview {
  llm_status: string
  phoenix_running: boolean
  langfuse_configured: boolean
  total_documents: number
  total_chunks: number
  qa_calls_today: number
  avg_latency_ms: number | null
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function fetchOverview(): Promise<MonitoringOverview | null> {
  const res = await fetch(`${API_BASE}/monitoring/overview`)
  if (!res.ok) return null
  return res.json() as Promise<MonitoringOverview>
}

async function fetchTraces(): Promise<TracesResponse> {
  const res = await fetch(`${API_BASE}/monitoring/traces`)
  if (!res.ok) return { traces: [] }
  return res.json() as Promise<TracesResponse>
}

// ---------------------------------------------------------------------------
// StatusBadge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const isError = status === "error"
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        isError ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"
      }`}
    >
      {isError ? "error" : "ok"}
    </span>
  )
}

// ---------------------------------------------------------------------------
// TraceDetailPanel — slides in from right when a row is selected
// ---------------------------------------------------------------------------

function TraceDetailPanel({
  trace,
  onClose,
}: {
  trace: TraceItem
  onClose: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      {/* Panel */}
      <div className="relative z-10 flex h-full w-full max-w-lg flex-col bg-background shadow-xl">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h3 className="font-semibold text-foreground">Span Details</h3>
          <button
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <XIcon size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-auto p-4">
          <div className="mb-4 flex flex-col gap-1 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Operation</span>
              <span className="font-medium text-foreground">{trace.operation_name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Span ID</span>
              <span className="font-mono text-xs text-foreground">{trace.span_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Trace ID</span>
              <span className="font-mono text-xs text-foreground">{trace.trace_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Duration</span>
              <span className="text-foreground">{trace.duration_ms.toFixed(1)} ms</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Status</span>
              <StatusBadge status={trace.status} />
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Start time</span>
              <span className="text-foreground">
                {trace.start_time ? new Date(trace.start_time).toLocaleString() : "—"}
              </span>
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <p className="text-xs font-semibold text-muted-foreground">Attributes</p>
            <pre className="overflow-auto rounded bg-secondary p-3 text-xs text-foreground">
              {JSON.stringify(trace.attributes, null, 2)}
            </pre>
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// StatCard
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  accent,
}: {
  label: string
  value: string
  accent?: "green" | "red" | "gray"
}) {
  const colorClass =
    accent === "green"
      ? "text-green-600"
      : accent === "red"
        ? "text-red-600"
        : "text-foreground"

  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-card p-3">
      <span className={`text-lg font-bold ${colorClass}`}>{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Monitoring page
// ---------------------------------------------------------------------------

export default function Monitoring() {
  const [overview, setOverview] = useState<MonitoringOverview | null>(null)
  const [traces, setTraces] = useState<TraceItem[]>([])
  const [tracesMessage, setTracesMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedTrace, setSelectedTrace] = useState<TraceItem | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      const [ov, tr] = await Promise.all([fetchOverview(), fetchTraces()])
      if (cancelled) return
      setOverview(ov)
      setTraces(tr.traces)
      setTracesMessage(tr.message ?? null)
      setLoading(false)
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 size={24} className="animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6 px-6 py-8">
      <h1 className="text-2xl font-semibold text-foreground">Monitoring</h1>

      {/* Overview cards */}
      {overview && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <StatCard label="LLM Model" value={overview.llm_status} />
          <StatCard
            label="Phoenix"
            value={overview.phoenix_running ? "Running" : "Offline"}
            accent={overview.phoenix_running ? "green" : "red"}
          />
          <StatCard
            label="Langfuse"
            value={overview.langfuse_configured ? "Configured" : "Not set"}
            accent={overview.langfuse_configured ? "green" : "gray"}
          />
          <StatCard label="Documents" value={String(overview.total_documents)} />
          <StatCard label="Chunks" value={String(overview.total_chunks)} />
          <StatCard label="QA calls today" value={String(overview.qa_calls_today)} />
        </div>
      )}

      {/* Traces table */}
      <div className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold text-foreground">Recent Traces</h2>
        {tracesMessage && (
          <p className="text-sm text-muted-foreground">{tracesMessage}</p>
        )}

        {traces.length === 0 ? (
          <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
            No traces available.
          </div>
        ) : (
          <div className="overflow-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/50">
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">
                    Timestamp
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">
                    Operation
                  </th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">
                    Duration
                  </th>
                  <th className="px-4 py-2 text-center text-xs font-semibold text-muted-foreground">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {traces.map((t) => (
                  <tr
                    key={t.span_id || `${t.trace_id}-${t.start_time}`}
                    onClick={() => setSelectedTrace(t)}
                    className="cursor-pointer border-b border-border last:border-0 hover:bg-accent"
                  >
                    <td className="px-4 py-2 text-xs text-muted-foreground">
                      {t.start_time ? new Date(t.start_time).toLocaleTimeString() : "—"}
                    </td>
                    <td className="px-4 py-2 font-medium text-foreground">
                      {t.operation_name}
                    </td>
                    <td className="px-4 py-2 text-right text-muted-foreground">
                      {t.duration_ms.toFixed(1)} ms
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
      </div>

      {/* Trace detail panel */}
      {selectedTrace && (
        <TraceDetailPanel trace={selectedTrace} onClose={() => setSelectedTrace(null)} />
      )}
    </div>
  )
}
