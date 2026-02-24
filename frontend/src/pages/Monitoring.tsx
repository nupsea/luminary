/**
 * Monitoring tab — complete metrics dashboard.
 *
 * Sections:
 *   1. System Status — Ollama, Phoenix, Langfuse, Active Model
 *   2. RAG Quality — grouped BarChart per dataset (HR@5, MRR, Faithfulness, AR, CP)
 *   3. Model Usage — PieChart (local vs cloud) + BarChart (latency by model)
 *   4. Ingestion Queue — in-progress documents
 *   5. Recent Traces — last 50 Phoenix spans
 *   6. Eval Runs — table with HR@5 row coloring
 */

import { useEffect, useState } from "react"
import { Loader2, X as XIcon } from "lucide-react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

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

interface EvalRun {
  id: string
  dataset_name: string
  model_used: string
  run_at: string
  hit_rate_5: number | null
  mrr: number | null
  faithfulness: number | null
  answer_relevance: number | null
  context_precision: number | null
  context_recall: number | null
}

interface ModelUsageItem {
  model: string
  call_count: number
  avg_latency_ms: number | null
}

interface LLMSettings {
  processing_mode: string
  active_model: string
}

interface Document {
  id: string
  title: string
  stage: string
  content_type: string
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

async function fetchEvalRuns(): Promise<EvalRun[]> {
  const res = await fetch(`${API_BASE}/monitoring/evals`)
  if (!res.ok) return []
  return res.json() as Promise<EvalRun[]>
}

async function fetchModelUsage(): Promise<ModelUsageItem[]> {
  const res = await fetch(`${API_BASE}/monitoring/model-usage`)
  if (!res.ok) return []
  return res.json() as Promise<ModelUsageItem[]>
}

async function fetchLLMSettings(): Promise<LLMSettings | null> {
  const res = await fetch(`${API_BASE}/settings/llm`)
  if (!res.ok) return null
  return res.json() as Promise<LLMSettings>
}

async function fetchDocuments(): Promise<Document[]> {
  const res = await fetch(`${API_BASE}/documents`)
  if (!res.ok) return []
  return res.json() as Promise<Document[]>
}

// ---------------------------------------------------------------------------
// Helper components
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

function StatusIndicator({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-card p-3">
      <div className="flex items-center gap-2">
        <span
          className={`inline-block h-2.5 w-2.5 rounded-full ${ok ? "bg-green-500" : "bg-red-500"}`}
        />
        <span className={`text-sm font-semibold ${ok ? "text-green-700" : "text-red-600"}`}>
          {ok ? "Online" : "Offline"}
        </span>
      </div>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

function ModelBadge({ model }: { model: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-card p-3">
      <span className="truncate text-sm font-semibold text-foreground">{model}</span>
      <span className="text-xs text-muted-foreground">Active Model</span>
    </div>
  )
}

function TraceDetailPanel({
  trace,
  onClose,
}: {
  trace: TraceItem
  onClose: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
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
// Empty state
// ---------------------------------------------------------------------------

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
      {message}
    </div>
  )
}

// ---------------------------------------------------------------------------
// RAG Quality BarChart — grouped by dataset
// ---------------------------------------------------------------------------

const METRIC_BARS = [
  { key: "hit_rate_5", label: "HR@5", color: "#6366f1" },
  { key: "mrr", label: "MRR", color: "#0ea5e9" },
  { key: "faithfulness", label: "Faithfulness", color: "#22c55e" },
  { key: "answer_relevance", label: "Answer Rel.", color: "#f59e0b" },
  { key: "context_precision", label: "Ctx Prec.", color: "#ec4899" },
]

function buildRagChartData(evalRuns: EvalRun[]) {
  // Latest run per dataset
  const byDataset: Record<string, EvalRun> = {}
  for (const run of evalRuns) {
    if (!byDataset[run.dataset_name]) {
      byDataset[run.dataset_name] = run
    }
  }
  return Object.entries(byDataset).map(([dataset, run]) => ({
    dataset,
    hit_rate_5: run.hit_rate_5 ?? 0,
    mrr: run.mrr ?? 0,
    faithfulness: run.faithfulness ?? 0,
    answer_relevance: run.answer_relevance ?? 0,
    context_precision: run.context_precision ?? 0,
  }))
}

function RAGQualityChart({ evalRuns }: { evalRuns: EvalRun[] }) {
  const data = buildRagChartData(evalRuns)
  if (data.length === 0) {
    return <EmptyState message="No eval runs yet. Run evals/run_eval.py to populate." />
  }
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="dataset" tick={{ fontSize: 11 }} />
        <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
        <Tooltip formatter={(v: number | string | undefined) => (typeof v === "number" ? v.toFixed(3) : (v ?? "—"))} />
        <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
        <ReferenceLine y={0.65} stroke="#6366f1" strokeDasharray="4 4" label={{ value: "HR@5 target 0.65", position: "insideTopRight", fontSize: 10 }} />
        <ReferenceLine y={0.9} stroke="#22c55e" strokeDasharray="4 4" label={{ value: "Faith. target 0.9", position: "insideBottomRight", fontSize: 10 }} />
        {METRIC_BARS.map((m) => (
          <Bar key={m.key} dataKey={m.key} name={m.label} fill={m.color} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

// ---------------------------------------------------------------------------
// Model Usage — PieChart + latency BarChart
// ---------------------------------------------------------------------------

const PIE_COLORS = ["#6366f1", "#0ea5e9", "#22c55e", "#f59e0b", "#ec4899"]

function buildPieData(modelUsage: ModelUsageItem[]) {
  const local = modelUsage
    .filter((m) => m.model.startsWith("ollama/"))
    .reduce((s, m) => s + m.call_count, 0)
  const cloud = modelUsage
    .filter((m) => !m.model.startsWith("ollama/"))
    .reduce((s, m) => s + m.call_count, 0)
  return [
    { name: "Local (Ollama)", value: local },
    { name: "Cloud", value: cloud },
  ].filter((d) => d.value > 0)
}

function ModelUsageSection({ modelUsage }: { modelUsage: ModelUsageItem[] }) {
  if (modelUsage.length === 0) {
    return <EmptyState message="No QA calls recorded yet." />
  }
  const pieData = buildPieData(modelUsage)
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {/* PieChart — local vs cloud */}
      <div className="flex flex-col gap-2">
        <p className="text-sm font-medium text-muted-foreground">Local vs Cloud</p>
        {pieData.length > 0 ? (
          <ResponsiveContainer width="100%" height={180}>
            <PieChart>
              <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={70} label={({ name, percent }: { name?: string; percent?: number }) => `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%`}>
                {pieData.map((_, i) => (
                  <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        ) : (
          <EmptyState message="No calls recorded." />
        )}
      </div>

      {/* BarChart — calls per model */}
      <div className="flex flex-col gap-2">
        <p className="text-sm font-medium text-muted-foreground">Calls by Model</p>
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={modelUsage} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="model" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Bar dataKey="call_count" name="Calls" fill="#6366f1" />
          </BarChart>
        </ResponsiveContainer>
      </div>
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
  const [evalRuns, setEvalRuns] = useState<EvalRun[]>([])
  const [modelUsage, setModelUsage] = useState<ModelUsageItem[]>([])
  const [llmSettings, setLLMSettings] = useState<LLMSettings | null>(null)
  const [ingestingDocs, setIngestingDocs] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedTrace, setSelectedTrace] = useState<TraceItem | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      const [ov, tr, evs, usage, llm, docs] = await Promise.all([
        fetchOverview(),
        fetchTraces(),
        fetchEvalRuns(),
        fetchModelUsage(),
        fetchLLMSettings(),
        fetchDocuments(),
      ])
      if (cancelled) return
      setOverview(ov)
      setTraces(tr.traces)
      setTracesMessage(tr.message ?? null)
      setEvalRuns(evs)
      setModelUsage(usage)
      setLLMSettings(llm)
      setIngestingDocs(docs.filter((d) => d.stage !== "complete"))
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

  const ollamaOnline = llmSettings?.processing_mode === "local"
  const activeModel = llmSettings?.active_model ?? overview?.llm_status ?? "—"

  return (
    <div className="flex flex-col gap-8 px-6 py-8">
      <h1 className="text-2xl font-semibold text-foreground">Monitoring</h1>

      {/* 1. System Status */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">System Status</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatusIndicator ok={ollamaOnline} label="Ollama" />
          <StatusIndicator ok={overview?.phoenix_running ?? false} label="Phoenix" />
          <StatusIndicator ok={overview?.langfuse_configured ?? false} label="Langfuse" />
          <ModelBadge model={activeModel} />
        </div>
        {overview && (
          <div className="grid grid-cols-3 gap-3">
            <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card px-4 py-3">
              <span className="text-lg font-bold text-foreground">{overview.total_documents}</span>
              <span className="text-xs text-muted-foreground">Documents</span>
            </div>
            <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card px-4 py-3">
              <span className="text-lg font-bold text-foreground">{overview.total_chunks}</span>
              <span className="text-xs text-muted-foreground">Chunks</span>
            </div>
            <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card px-4 py-3">
              <span className="text-lg font-bold text-foreground">{overview.qa_calls_today}</span>
              <span className="text-xs text-muted-foreground">QA calls today</span>
            </div>
          </div>
        )}
      </section>

      {/* 2. RAG Quality */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">RAG Quality</h2>
        <RAGQualityChart evalRuns={evalRuns} />
      </section>

      {/* 3. Model Usage */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Model Usage</h2>
        <ModelUsageSection modelUsage={modelUsage} />
      </section>

      {/* 4. Ingestion Queue */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Ingestion Queue</h2>
        {ingestingDocs.length === 0 ? (
          <EmptyState message="No documents currently ingesting." />
        ) : (
          <div className="flex flex-col gap-1 rounded-lg border border-border">
            {ingestingDocs.map((doc, i) => (
              <div
                key={doc.id}
                className={`flex items-center justify-between px-4 py-2 text-sm ${
                  i > 0 ? "border-t border-border" : ""
                }`}
              >
                <span className="font-medium text-foreground">{doc.title}</span>
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                  {doc.stage}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 5. Recent Traces */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Recent Traces</h2>
        {tracesMessage && (
          <p className="text-sm text-muted-foreground">{tracesMessage}</p>
        )}
        {traces.length === 0 ? (
          <EmptyState message="No traces available." />
        ) : (
          <div className="overflow-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/50">
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Timestamp</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Operation</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">Duration</th>
                  <th className="px-4 py-2 text-center text-xs font-semibold text-muted-foreground">Status</th>
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
                    <td className="px-4 py-2 font-medium text-foreground">{t.operation_name}</td>
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
      </section>

      {/* 6. Eval Runs */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Eval Runs</h2>
        {evalRuns.length === 0 ? (
          <EmptyState message="No evaluation runs yet. Run evals/run_eval.py to populate." />
        ) : (
          <div className="overflow-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/50">
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Dataset</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Run At</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">HR@5</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">MRR</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">Faithfulness</th>
                </tr>
              </thead>
              <tbody>
                {evalRuns.map((run) => {
                  const hr5 = run.hit_rate_5
                  const rowBg =
                    hr5 !== null && hr5 < 0.5
                      ? "bg-red-50 dark:bg-red-950/30"
                      : hr5 !== null && hr5 > 0.7
                        ? "bg-green-50 dark:bg-green-950/30"
                        : ""
                  return (
                    <tr key={run.id} className={`border-b border-border last:border-0 ${rowBg}`}>
                      <td className="px-4 py-2 font-medium text-foreground">{run.dataset_name}</td>
                      <td className="px-4 py-2 text-xs text-muted-foreground">
                        {new Date(run.run_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-2 text-right text-foreground">
                        {hr5 !== null ? hr5.toFixed(2) : "—"}
                      </td>
                      <td className="px-4 py-2 text-right text-foreground">
                        {run.mrr !== null ? run.mrr.toFixed(2) : "—"}
                      </td>
                      <td className="px-4 py-2 text-right text-foreground">
                        {run.faithfulness !== null ? run.faithfulness.toFixed(2) : "—"}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Trace detail panel */}
      {selectedTrace && (
        <TraceDetailPanel trace={selectedTrace} onClose={() => setSelectedTrace(null)} />
      )}
    </div>
  )
}
