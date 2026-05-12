import { useEffect, useMemo, useState } from "react"
import { AlertTriangle } from "lucide-react"
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { apiGet } from "@/lib/apiClient"

interface EvalHistoryItem {
  dataset: string
  timestamp: string
  hr5: number | null
  mrr: number | null
  faithfulness: number | null
}

interface EvalRegression {
  dataset: string
  metric: string
  current_value: number
  baseline_value: number
  drop_pct: number
  eval_kind: string | null
}

export function EvalTrendsPanel({ history }: { history: EvalHistoryItem[] }) {
  const [dataset, setDataset] = useState("")
  const [regressions, setRegressions] = useState<EvalRegression[]>([])
  const [expanded, setExpanded] = useState(false)

  const datasets = useMemo(
    () => Array.from(new Set(history.map((row) => row.dataset))).sort(),
    [history],
  )

  useEffect(() => {
    if (!dataset && datasets.length > 0) setDataset(datasets[0])
  }, [dataset, datasets])

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const data = await apiGet<EvalRegression[]>("/monitoring/evals/regressions")
        if (!cancelled) setRegressions(data)
      } catch {
        // best-effort polling; ignore failures
      }
    }
    void load()
    const timer = window.setInterval(() => void load(), 60_000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  const rows = history
    .filter((row) => row.dataset === dataset)
    .map((row) => ({
      label: new Date(row.timestamp).toLocaleDateString(),
      hit_rate_5: row.hr5,
      mrr: row.mrr,
      faithfulness: row.faithfulness,
    }))

  return (
    <div className="grid gap-3 rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Eval Trends</h2>
          <p className="text-xs text-muted-foreground">Latest HR@5, MRR, and faithfulness by dataset.</p>
        </div>
        <div className="flex items-center gap-2">
          {regressions.length > 0 && (
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2.5 py-1 text-xs font-medium text-red-700"
              onClick={() => setExpanded((value) => !value)}
            >
              <AlertTriangle className="h-3.5 w-3.5" />
              {regressions.length} regression{regressions.length === 1 ? "" : "s"}
            </button>
          )}
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={dataset}
            onChange={(event) => setDataset(event.target.value)}
          >
            {datasets.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {expanded && (
        <div className="grid gap-1 rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          {regressions.map((item) => (
            <div key={`${item.dataset}-${item.metric}-${item.eval_kind || "none"}`}>
              {item.dataset} {item.metric}: {(item.drop_pct * 100).toFixed(1)}% drop
            </div>
          ))}
        </div>
      )}

      {rows.length === 0 ? (
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
          No trend data.
        </div>
      ) : (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="hit_rate_5" stroke="#2563eb" dot={false} />
              <Line type="monotone" dataKey="mrr" stroke="#16a34a" dot={false} />
              <Line type="monotone" dataKey="faithfulness" stroke="#9333ea" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
