/**
 * Monitoring tab — complete metrics dashboard.
 *
 * Sections:
 *   1. System Status — Ollama, Phoenix, Langfuse, Active Model
 *   2. RAG Quality — grouped BarChart per dataset (HR@5, MRR, Faithfulness, AR, CP)
 *   3. Retrieval Quality Over Time — HR@5 sparkline per dataset
 *   4. Model Usage — PieChart (local vs cloud) + BarChart (latency by model)
 *   5. Ingestion Queue — in-progress documents
 *   6. Recent Traces — last 50 Phoenix spans
 *   7. Eval Runs — table with HR@5 row coloring
 *
 * Each section fetches independently: if one endpoint fails the rest render normally.
 */

import { useEffect, useState } from "react"
import { X as XIcon } from "lucide-react"
import { toast } from "sonner"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { Skeleton } from "@/components/ui/skeleton"
import { logger } from "@/lib/logger"

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

interface EvalHistoryItem {
  timestamp: string
  dataset: string
  model: string
  hr5: number | null
  mrr: number | null
  faithfulness: number | null
  passed: boolean
}

interface LLMSettings {
  processing_mode: string
  active_model: string
}

interface EvalResultItem {
  dataset: string
  run_at: string
  hit_rate_5: number | null
  mrr: number | null
  faithfulness: number | null
  context_precision: number | null
  context_recall: number | null
  answer_relevancy: number | null
  passed_thresholds: boolean | null
}

interface PhoenixUrl {
  url: string
  enabled: boolean
}

interface Document {
  id: string
  title: string
  stage: string
  content_type: string
}

// ---------------------------------------------------------------------------
// Per-section state
// ---------------------------------------------------------------------------

interface SectionState<T> {
  loading: boolean
  data: T
  error: boolean
}

function initSection<T>(data: T): SectionState<T> {
  return { loading: true, data, error: false }
}

// ---------------------------------------------------------------------------
// API — throw on non-ok so catch handlers set error: true
// ---------------------------------------------------------------------------

async function fetchOverview(): Promise<MonitoringOverview> {
  const res = await fetch(`${API_BASE}/monitoring/overview`)
  if (!res.ok) throw new Error("overview failed")
  return res.json() as Promise<MonitoringOverview>
}

async function fetchTraces(): Promise<TracesResponse> {
  const res = await fetch(`${API_BASE}/monitoring/traces`)
  if (!res.ok) throw new Error("traces failed")
  return res.json() as Promise<TracesResponse>
}

async function fetchEvalRuns(): Promise<EvalRun[]> {
  const res = await fetch(`${API_BASE}/monitoring/evals`)
  if (!res.ok) throw new Error("evals failed")
  return res.json() as Promise<EvalRun[]>
}

async function fetchModelUsage(): Promise<ModelUsageItem[]> {
  const res = await fetch(`${API_BASE}/monitoring/model-usage`)
  if (!res.ok) throw new Error("model-usage failed")
  return res.json() as Promise<ModelUsageItem[]>
}

async function fetchLLMSettings(): Promise<LLMSettings> {
  const res = await fetch(`${API_BASE}/settings/llm`)
  if (!res.ok) throw new Error("llm-settings failed")
  return res.json() as Promise<LLMSettings>
}

async function fetchDocuments(): Promise<Document[]> {
  const res = await fetch(`${API_BASE}/documents`)
  if (!res.ok) throw new Error("documents failed")
  const data = (await res.json()) as { items?: Document[] } | Document[]
  // handle both paginated and legacy list responses
  if (Array.isArray(data)) return data
  return (data as { items?: Document[] }).items ?? []
}

async function fetchEvalHistory(): Promise<EvalHistoryItem[]> {
  const res = await fetch(`${API_BASE}/monitoring/eval-history`)
  if (!res.ok) throw new Error("eval-history failed")
  return res.json() as Promise<EvalHistoryItem[]>
}

async function fetchPhoenixUrl(): Promise<PhoenixUrl> {
  const res = await fetch(`${API_BASE}/monitoring/phoenix-url`)
  if (!res.ok) throw new Error("phoenix-url failed")
  return res.json() as Promise<PhoenixUrl>
}

async function fetchEvalResults(): Promise<EvalResultItem[]> {
  const res = await fetch(`${API_BASE}/evals/results`)
  if (!res.ok) throw new Error("evals/results failed")
  return res.json() as Promise<EvalResultItem[]>
}

async function triggerEvalRun(dataset: string): Promise<void> {
  const res = await fetch(`${API_BASE}/evals/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset }),
  })
  if (!res.ok) throw new Error(`evals/run failed: ${res.status}`)
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
// Empty / Error states
// ---------------------------------------------------------------------------

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
      {message}
    </div>
  )
}

function SectionErrorCard({ name }: { name: string }) {
  return (
    <div className="flex h-24 items-center justify-center rounded-lg border border-red-200 bg-red-50 text-sm text-red-600">
      Could not load {name}
    </div>
  )
}

function SectionSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-3">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  )
}

function MetricCardSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} className="h-16 w-full rounded-lg" />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Eval History Sparkline — HR@5 over time per dataset
// ---------------------------------------------------------------------------

const DATASET_COLORS: Record<string, string> = {
  book: "#6366f1",
  paper: "#0ea5e9",
  notes: "#22c55e",
  conversation: "#f59e0b",
  code: "#ec4899",
}

function buildSparklineData(history: EvalHistoryItem[]) {
  const datasets = Array.from(new Set(history.map((h) => h.dataset)))
  const allTimestamps = Array.from(new Set(history.map((h) => h.timestamp))).sort()
  return allTimestamps.map((ts, i) => {
    const row: Record<string, number | string> = { run: i + 1, ts }
    for (const ds of datasets) {
      const item = history.find((h) => h.timestamp === ts && h.dataset === ds)
      if (item && item.hr5 !== null) {
        row[ds] = item.hr5
      }
    }
    return row
  })
}

function EvalHistorySparkline({ history }: { history: EvalHistoryItem[] }) {
  if (history.length === 0) {
    return <EmptyState message="No eval history yet. Run make eval to populate." />
  }
  const data = buildSparklineData(history)
  const datasets = Array.from(new Set(history.map((h) => h.dataset)))
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="run" label={{ value: "Run", position: "insideBottomRight", offset: -4, fontSize: 10 }} tick={{ fontSize: 10 }} />
        <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} />
        <Tooltip
          formatter={(v: number | string | undefined, name: string | undefined) =>
            typeof v === "number" ? [v.toFixed(3), name ?? ""] : [(v ?? "—"), name ?? ""]
          }
        />
        <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
        <ReferenceLine y={0.6} stroke="#6366f1" strokeDasharray="4 4" label={{ value: "threshold 0.60", position: "insideTopRight", fontSize: 9 }} />
        {datasets.map((ds) => (
          <Line
            key={ds}
            type="monotone"
            dataKey={ds}
            name={ds}
            stroke={DATASET_COLORS[ds] ?? "#94a3b8"}
            dot={{ r: 3 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
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
// Traces card — Phoenix link
// ---------------------------------------------------------------------------

function TracesCard({ phoenix }: { phoenix: PhoenixUrl | null }) {
  const enabled = phoenix?.enabled ?? false
  const url = phoenix?.url ?? "http://localhost:6006"
  return (
    <div className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex items-center gap-2">
        <span
          className={`inline-block h-2.5 w-2.5 rounded-full ${enabled ? "bg-green-500" : "bg-gray-400"}`}
        />
        <span className="text-sm font-medium text-foreground">Arize Phoenix — Distributed Tracing</span>
      </div>
      <button
        disabled={!enabled}
        onClick={() => window.open(url, "_blank")}
        title={
          enabled
            ? "Open Phoenix UI"
            : "Start Phoenix: cd backend && uv run python -m phoenix.server.main"
        }
        className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
          enabled
            ? "bg-primary text-primary-foreground hover:bg-primary/90"
            : "cursor-not-allowed bg-secondary text-muted-foreground"
        }`}
      >
        View Traces
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// EvalPanel — RAGAS eval results from /evals/results with threshold coloring
// ---------------------------------------------------------------------------

const EVAL_THRESHOLDS: Record<string, number> = {
  hit_rate_5: 0.60,
  mrr: 0.45,
  faithfulness: 0.65,
  context_precision: 0.65,
}

function scoreColor(value: number | null, metricKey: string): string {
  if (value === null) return "text-muted-foreground"
  const threshold = EVAL_THRESHOLDS[metricKey]
  if (threshold === undefined) return "text-foreground"
  if (value >= threshold) return "text-green-700 dark:text-green-400 font-semibold"
  if (value >= threshold * 0.75) return "text-amber-600 dark:text-amber-400 font-semibold"
  return "text-muted-foreground"
}

function EvalPanel() {
  const [state, setState] = useState<SectionState<EvalResultItem[]>>(initSection([]))
  const [runningDatasets, setRunningDatasets] = useState<Set<string>>(new Set())

  useEffect(() => {
    let cancelled = false
    fetchEvalResults()
      .then((d) => {
        if (!cancelled) setState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] EvalPanel fetch failed", e)
        if (!cancelled) setState({ loading: false, data: [], error: true })
      })
    return () => {
      cancelled = true
    }
  }, [])

  function handleRunEval(dataset: string) {
    setRunningDatasets((prev) => new Set(prev).add(dataset))
    triggerEvalRun(dataset)
      .then(() => {
        toast.success(`Eval run started for dataset: ${dataset}`)
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] EvalPanel run failed", dataset, e)
        toast.error(`Failed to start eval for dataset: ${dataset}`)
      })
      .finally(() => {
        setRunningDatasets((prev) => {
          const next = new Set(prev)
          next.delete(dataset)
          return next
        })
      })
  }

  if (state.loading) {
    return <SectionSkeleton rows={3} />
  }
  if (state.error) {
    return <SectionErrorCard name="RAGAS Eval Results" />
  }
  if (state.data.length === 0) {
    return <EmptyState message="No eval results yet. Run evals/run_eval.py to populate." />
  }

  return (
    <div className="overflow-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-secondary/50">
            <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Dataset</th>
            <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Run At</th>
            <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">HR@5</th>
            <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">MRR</th>
            <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">Faithfulness</th>
            <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">Ctx Precision</th>
            <th className="px-4 py-2 text-center text-xs font-semibold text-muted-foreground">Action</th>
          </tr>
        </thead>
        <tbody>
          {state.data.map((item) => (
            <tr key={item.dataset} className="border-b border-border last:border-0">
              <td className="px-4 py-2 font-medium text-foreground">{item.dataset}</td>
              <td className="px-4 py-2 text-xs text-muted-foreground">
                {item.run_at ? new Date(item.run_at).toLocaleString() : "—"}
              </td>
              <td className={`px-4 py-2 text-right ${scoreColor(item.hit_rate_5, "hit_rate_5")}`}>
                {item.hit_rate_5 !== null ? item.hit_rate_5.toFixed(3) : "—"}
              </td>
              <td className={`px-4 py-2 text-right ${scoreColor(item.mrr, "mrr")}`}>
                {item.mrr !== null ? item.mrr.toFixed(3) : "—"}
              </td>
              <td className={`px-4 py-2 text-right ${scoreColor(item.faithfulness, "faithfulness")}`}>
                {item.faithfulness !== null ? item.faithfulness.toFixed(3) : "—"}
              </td>
              <td className={`px-4 py-2 text-right ${scoreColor(item.context_precision, "context_precision")}`}>
                {item.context_precision !== null ? item.context_precision.toFixed(3) : "—"}
              </td>
              <td className="px-4 py-2 text-center">
                <button
                  onClick={() => handleRunEval(item.dataset)}
                  disabled={runningDatasets.has(item.dataset)}
                  className="rounded px-2 py-1 text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
                >
                  {runningDatasets.has(item.dataset) ? "Starting..." : "Run Eval"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Monitoring page
// ---------------------------------------------------------------------------

export default function Monitoring() {
  const [overviewState, setOverviewState] = useState<SectionState<MonitoringOverview | null>>(
    initSection(null),
  )
  const [tracesState, setTracesState] = useState<SectionState<TracesResponse>>(
    initSection({ traces: [] }),
  )
  const [evalRunsState, setEvalRunsState] = useState<SectionState<EvalRun[]>>(initSection([]))
  const [evalHistState, setEvalHistState] = useState<SectionState<EvalHistoryItem[]>>(
    initSection([]),
  )
  const [modelUsageState, setModelUsageState] = useState<SectionState<ModelUsageItem[]>>(
    initSection([]),
  )
  const [llmState, setLlmState] = useState<SectionState<LLMSettings | null>>(initSection(null))
  const [docsState, setDocsState] = useState<SectionState<Document[]>>(initSection([]))
  const [phoenixUrlState, setPhoenixUrlState] = useState<SectionState<PhoenixUrl | null>>(
    initSection(null),
  )

  const [selectedTrace, setSelectedTrace] = useState<TraceItem | null>(null)

  useEffect(() => {
    let cancelled = false

    fetchOverview()
      .then((d) => {
        if (!cancelled) setOverviewState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", "System Status", e)
        if (!cancelled) setOverviewState({ loading: false, data: null, error: true })
      })

    fetchTraces()
      .then((d) => {
        if (!cancelled) setTracesState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", "Recent Traces", e)
        if (!cancelled) setTracesState({ loading: false, data: { traces: [] }, error: true })
      })

    fetchEvalRuns()
      .then((d) => {
        if (!cancelled) setEvalRunsState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", "Eval Runs", e)
        if (!cancelled) setEvalRunsState({ loading: false, data: [], error: true })
      })

    fetchEvalHistory()
      .then((d) => {
        if (!cancelled) setEvalHistState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", "Eval History", e)
        if (!cancelled) setEvalHistState({ loading: false, data: [], error: true })
      })

    fetchModelUsage()
      .then((d) => {
        if (!cancelled) setModelUsageState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", "Model Usage", e)
        if (!cancelled) setModelUsageState({ loading: false, data: [], error: true })
      })

    fetchLLMSettings()
      .then((d) => {
        if (!cancelled) setLlmState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", "LLM Settings", e)
        if (!cancelled) setLlmState({ loading: false, data: null, error: true })
      })

    fetchDocuments()
      .then((d) => {
        if (!cancelled) setDocsState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", "Ingestion Queue", e)
        if (!cancelled) setDocsState({ loading: false, data: [], error: true })
      })

    const loadPhoenixUrl = () => {
      fetchPhoenixUrl()
        .then((d) => {
          if (!cancelled) setPhoenixUrlState({ loading: false, data: d, error: false })
        })
        .catch((e: unknown) => {
          logger.warn("[Monitoring] section failed", "Phoenix URL", e)
          if (!cancelled) setPhoenixUrlState({ loading: false, data: null, error: true })
        })
    }
    loadPhoenixUrl()
    const phoenixInterval = setInterval(loadPhoenixUrl, 30_000)

    return () => {
      cancelled = true
      clearInterval(phoenixInterval)
    }
  }, [])

  const ollamaOnline = llmState.data?.processing_mode === "local"
  const activeModel = llmState.data?.active_model ?? overviewState.data?.llm_status ?? "—"
  const ingestingDocs = docsState.data.filter((d) => d.stage !== "complete")

  return (
    <div className="flex flex-col gap-8 px-6 py-8">
      <h1 className="text-2xl font-semibold text-foreground">Monitoring</h1>

      {/* 0. Traces link card */}
      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold text-foreground">Traces</h2>
        {phoenixUrlState.loading ? (
          <Skeleton className="h-12 w-full rounded-lg" />
        ) : phoenixUrlState.error ? (
          <div className="flex h-12 items-center justify-center rounded-lg border border-red-200 bg-red-50 text-sm text-red-600">
            Could not check Phoenix status.
          </div>
        ) : (
          <TracesCard phoenix={phoenixUrlState.data} />
        )}
      </section>

      {/* 1. System Status */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">System Status</h2>
        {overviewState.loading || llmState.loading ? (
          <MetricCardSkeleton />
        ) : overviewState.error && llmState.error ? (
          <SectionErrorCard name="System Status" />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatusIndicator ok={ollamaOnline} label="Ollama" />
              <StatusIndicator ok={overviewState.data?.phoenix_running ?? false} label="Phoenix" />
              <StatusIndicator ok={overviewState.data?.langfuse_configured ?? false} label="Langfuse" />
              <ModelBadge model={activeModel} />
            </div>
            {overviewState.data && (
              <div className="grid grid-cols-3 gap-3">
                <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card px-4 py-3">
                  <span className="text-lg font-bold text-foreground">{overviewState.data.total_documents}</span>
                  <span className="text-xs text-muted-foreground">Documents</span>
                </div>
                <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card px-4 py-3">
                  <span className="text-lg font-bold text-foreground">{overviewState.data.total_chunks}</span>
                  <span className="text-xs text-muted-foreground">Chunks</span>
                </div>
                <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card px-4 py-3">
                  <span className="text-lg font-bold text-foreground">{overviewState.data.qa_calls_today}</span>
                  <span className="text-xs text-muted-foreground">QA calls today</span>
                </div>
              </div>
            )}
          </>
        )}
      </section>

      {/* 2. RAG Quality */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">RAG Quality</h2>
        {evalRunsState.loading ? (
          <SectionSkeleton rows={4} />
        ) : evalRunsState.error ? (
          <SectionErrorCard name="RAG Quality" />
        ) : (
          <RAGQualityChart evalRuns={evalRunsState.data} />
        )}
      </section>

      {/* 3. HR@5 Over Time */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Retrieval Quality Over Time</h2>
        <p className="text-xs text-muted-foreground">HR@5 per dataset across eval runs. Dashed line = 0.60 threshold.</p>
        {evalHistState.loading ? (
          <SectionSkeleton rows={3} />
        ) : evalHistState.error ? (
          <SectionErrorCard name="Retrieval Quality Over Time" />
        ) : (
          <EvalHistorySparkline history={evalHistState.data} />
        )}
      </section>

      {/* 4. Model Usage */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Model Usage</h2>
        {modelUsageState.loading ? (
          <SectionSkeleton rows={3} />
        ) : modelUsageState.error ? (
          <SectionErrorCard name="Model Usage" />
        ) : (
          <ModelUsageSection modelUsage={modelUsageState.data} />
        )}
      </section>

      {/* 5. Ingestion Queue */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Ingestion Queue</h2>
        {docsState.loading ? (
          <SectionSkeleton rows={2} />
        ) : docsState.error ? (
          <SectionErrorCard name="Ingestion Queue" />
        ) : ingestingDocs.length === 0 ? (
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

      {/* 6. Recent Traces */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Recent Traces</h2>
        {tracesState.loading ? (
          <SectionSkeleton rows={5} />
        ) : tracesState.error ? (
          <SectionErrorCard name="Recent Traces" />
        ) : (
          <>
            {tracesState.data.message && (
              <p className="text-sm text-muted-foreground">{tracesState.data.message}</p>
            )}
            {tracesState.data.traces.length === 0 ? (
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
                    {tracesState.data.traces.map((t) => (
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
          </>
        )}
      </section>

      {/* 7a. RAGAS Eval Results — from /evals/results */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">RAGAS Eval Results</h2>
        <p className="text-xs text-muted-foreground">
          Latest result per dataset. Green = meets threshold, amber = close, grey = below. Click Run Eval to trigger a background eval run.
        </p>
        <EvalPanel />
      </section>

      {/* 7b. Eval Runs (legacy /monitoring/evals) */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Eval Runs</h2>
        {evalRunsState.loading ? (
          <SectionSkeleton rows={4} />
        ) : evalRunsState.error ? (
          <SectionErrorCard name="Eval Runs" />
        ) : evalRunsState.data.length === 0 ? (
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
                {evalRunsState.data.map((run) => {
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
