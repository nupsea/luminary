// Recharts-based visualisations for the Monitoring page:
//   - EvalHistorySparkline: HR@5 over time per dataset
//   - RAGQualityChart:      grouped bar chart of last run per dataset
//   - ModelUsageSection:    Pie (local vs cloud) + Bar (calls/model)
//   - TracesCard:           Phoenix link card

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

import { EmptyState } from "./SharedUI"
import type { EvalHistoryItem, EvalRun, ModelUsageItem, PhoenixUrl } from "./types"
import {
  DATASET_COLORS,
  METRIC_BARS,
  PIE_COLORS,
  buildPieData,
  buildRagChartData,
  buildSparklineData,
} from "./utils"

export function EvalHistorySparkline({ history }: { history: EvalHistoryItem[] }) {
  if (history.length === 0) {
    return <EmptyState message="No eval history yet. Run make eval to populate." />
  }
  const data = buildSparklineData(history)
  const datasets = Array.from(new Set(history.map((h) => h.dataset)))
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis
          dataKey="run"
          label={{
            value: "Run",
            position: "insideBottomRight",
            offset: -4,
            fontSize: 10,
          }}
          tick={{ fontSize: 10 }}
        />
        <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} />
        <Tooltip
          formatter={(v, name) =>
            typeof v === "number"
              ? [v.toFixed(3), name ?? ""]
              : [v ?? "—", name ?? ""]
          }
        />
        <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
        <ReferenceLine
          y={0.6}
          stroke="#6366f1"
          strokeDasharray="4 4"
          label={{ value: "threshold 0.60", position: "insideTopRight", fontSize: 9 }}
        />
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

export function RAGQualityChart({ evalRuns }: { evalRuns: EvalRun[] }) {
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
        <Tooltip formatter={(v) => (typeof v === "number" ? v.toFixed(3) : (v ?? "—"))} />
        <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
        <ReferenceLine
          y={0.65}
          stroke="#6366f1"
          strokeDasharray="4 4"
          label={{ value: "HR@5 target 0.65", position: "insideTopRight", fontSize: 10 }}
        />
        <ReferenceLine
          y={0.9}
          stroke="#22c55e"
          strokeDasharray="4 4"
          label={{ value: "Faith. target 0.9", position: "insideBottomRight", fontSize: 10 }}
        />
        {METRIC_BARS.map((m) => (
          <Bar key={m.key} dataKey={m.key} name={m.label} fill={m.color} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

export function ModelUsageSection({ modelUsage }: { modelUsage: ModelUsageItem[] }) {
  if (modelUsage.length === 0) {
    return <EmptyState message="No QA calls recorded yet." />
  }
  const pieData = buildPieData(modelUsage)
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {/* PieChart -- local vs cloud */}
      <div className="flex flex-col gap-2">
        <p className="text-sm font-medium text-muted-foreground">Local vs Cloud</p>
        {pieData.length > 0 ? (
          <ResponsiveContainer width="100%" height={180}>
            <PieChart>
              <Pie
                data={pieData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={70}
                label={({ name, percent }: { name?: string; percent?: number }) =>
                  `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%`
                }
              >
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

      {/* BarChart -- calls per model */}
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

export function TracesCard({ phoenix }: { phoenix: PhoenixUrl | null }) {
  const enabled = phoenix?.enabled ?? false
  const url = phoenix?.url ?? "http://localhost:6006"
  return (
    <div className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex items-center gap-2">
        <span
          className={`inline-block h-2.5 w-2.5 rounded-full ${enabled ? "bg-green-500" : "bg-gray-400"}`}
        />
        <span className="text-sm font-medium text-foreground">
          Arize Phoenix — Distributed Tracing
        </span>
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
