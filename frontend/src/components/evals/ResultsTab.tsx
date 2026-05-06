import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { Play } from "lucide-react"
import { toast } from "sonner"
import { Skeleton } from "@/components/ui/skeleton"
import { API_BASE } from "@/lib/config"
import { RunEvalDialog } from "./RunEvalDialog"

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

interface EvalHistoryItem {
  timestamp: string
  dataset: string
  model: string
  hr5: number | null
  mrr: number | null
  faithfulness: number | null
  passed: boolean
}

const EVAL_THRESHOLDS: Record<string, number> = {
  hit_rate_5: 0.6,
  mrr: 0.45,
  faithfulness: 0.65,
  context_precision: 0.65,
}

function scoreColor(value: number | null, key: string): string {
  if (value === null) return "text-muted-foreground"
  const threshold = EVAL_THRESHOLDS[key]
  if (threshold === undefined) return "text-foreground"
  if (value >= threshold) return "font-semibold text-green-700 dark:text-green-400"
  if (value >= threshold * 0.75) return "font-semibold text-amber-600 dark:text-amber-400"
  return "text-muted-foreground"
}

const DATASET_COLORS: Record<string, string> = {
  book: "#6366f1",
  book_time_machine: "#8b5cf6",
  book_alice: "#ec4899",
  book_odyssey: "#f97316",
  paper: "#0ea5e9",
  notes: "#22c55e",
  conversation: "#f59e0b",
  code: "#a78bfa",
}

const METRIC_BARS = [
  { key: "hit_rate_5", label: "HR@5", color: "#6366f1" },
  { key: "mrr", label: "MRR", color: "#0ea5e9" },
  { key: "faithfulness", label: "Faithfulness", color: "#22c55e" },
  { key: "answer_relevancy", label: "Answer Rel.", color: "#f59e0b" },
  { key: "context_precision", label: "Ctx Prec.", color: "#ec4899" },
]

async function fetchEvalResults(): Promise<EvalResultItem[]> {
  const res = await fetch(`${API_BASE}/evals/results`)
  if (!res.ok) throw new Error("Failed to fetch eval results")
  return res.json() as Promise<EvalResultItem[]>
}

async function fetchEvalHistory(): Promise<EvalHistoryItem[]> {
  const res = await fetch(`${API_BASE}/monitoring/eval-history`)
  if (!res.ok) throw new Error("Failed to fetch eval history")
  return res.json() as Promise<EvalHistoryItem[]>
}

function buildSparklineData(history: EvalHistoryItem[]) {
  const allTimestamps = Array.from(new Set(history.map((h) => h.timestamp))).sort()
  const datasets = Array.from(new Set(history.map((h) => h.dataset)))
  return allTimestamps.map((ts, i) => {
    const row: Record<string, number | string> = { run: i + 1 }
    for (const ds of datasets) {
      const item = history.find((h) => h.timestamp === ts && h.dataset === ds)
      if (item?.hr5 !== null && item?.hr5 !== undefined) row[ds] = item.hr5
    }
    return row
  })
}

export function ResultsTab({ onRunStarted }: { onRunStarted?: () => void }) {
  const qc = useQueryClient()
  const [runTarget, setRunTarget] = useState<string | null>(null)
  const [runDialogOpen, setRunDialogOpen] = useState(false)

  const resultsQuery = useQuery({
    queryKey: ["eval-results"],
    queryFn: fetchEvalResults,
    staleTime: 30_000,
  })

  const historyQuery = useQuery({
    queryKey: ["eval-history"],
    queryFn: fetchEvalHistory,
    staleTime: 60_000,
  })

  const runMutation = useMutation({
    mutationFn: async (payload: {
      judge_model: string
      check_citations: boolean
      max_questions: number
    }) => {
      if (!runTarget) throw new Error("No dataset selected")
      const res = await fetch(`${API_BASE}/evals/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dataset: runTarget,
          judge_model: payload.judge_model || null,
          check_citations: payload.check_citations,
          max_questions: payload.max_questions,
        }),
      })
      if (!res.ok) throw new Error("Failed to start eval run")
      return res.json()
    },
    onSuccess: () => {
      setRunDialogOpen(false)
      onRunStarted?.()
      void qc.invalidateQueries({ queryKey: ["eval-results"] })
      void qc.invalidateQueries({ queryKey: ["eval-runs"] })
      toast.success(`Eval started for ${runTarget ?? "dataset"} — check the Runs tab`)
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Run failed"),
  })

  const results = resultsQuery.data ?? []
  const history = historyQuery.data ?? []
  const sparklineDatasets = Array.from(new Set(history.map((h) => h.dataset)))
  const sparklineData = buildSparklineData(history)

  return (
    <div className="grid gap-8">
      {/* Latest results table */}
      <section className="grid gap-3">
        <h2 className="text-sm font-semibold">Latest Results per Dataset</h2>
        <p className="text-xs text-muted-foreground">
          Green = meets threshold, amber = close. Use a judge model when running to populate
          faithfulness and answer relevance.
        </p>
        {resultsQuery.isLoading ? (
          <div className="grid gap-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : resultsQuery.isError ? (
          <div className="rounded-md border border-destructive/30 p-3 text-sm text-destructive">
            Failed to load results.
          </div>
        ) : results.length === 0 ? (
          <div className="flex min-h-32 flex-col items-center justify-center gap-2 rounded-md border border-dashed text-center">
            <div className="text-sm font-medium">No eval results yet</div>
            <div className="text-xs text-muted-foreground">
              Run an eval from the Datasets tab to populate.
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">Dataset</th>
                  <th className="py-2 pr-3 font-medium">Run At</th>
                  <th className="py-2 pr-3 text-right font-medium">HR@5</th>
                  <th className="py-2 pr-3 text-right font-medium">MRR</th>
                  <th className="py-2 pr-3 text-right font-medium">Faithfulness</th>
                  <th className="py-2 pr-3 text-right font-medium">Ctx Prec.</th>
                  <th className="py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {results.map((item) => (
                  <tr key={item.dataset} className="border-b last:border-0">
                    <td className="py-2 pr-3 font-medium">{item.dataset}</td>
                    <td className="py-2 pr-3 text-muted-foreground">
                      {item.run_at ? new Date(item.run_at).toLocaleString() : "—"}
                    </td>
                    <td className={`py-2 pr-3 text-right ${scoreColor(item.hit_rate_5, "hit_rate_5")}`}>
                      {item.hit_rate_5 !== null ? item.hit_rate_5.toFixed(3) : "—"}
                    </td>
                    <td className={`py-2 pr-3 text-right ${scoreColor(item.mrr, "mrr")}`}>
                      {item.mrr !== null ? item.mrr.toFixed(3) : "—"}
                    </td>
                    <td
                      className={`py-2 pr-3 text-right ${scoreColor(item.faithfulness, "faithfulness")}`}
                    >
                      {item.faithfulness !== null ? item.faithfulness.toFixed(3) : "—"}
                    </td>
                    <td
                      className={`py-2 pr-3 text-right ${scoreColor(item.context_precision, "context_precision")}`}
                    >
                      {item.context_precision !== null ? item.context_precision.toFixed(3) : "—"}
                    </td>
                    <td className="py-2">
                      <button
                        type="button"
                        className="inline-flex h-7 items-center gap-1 rounded border px-2 text-xs font-medium hover:bg-accent"
                        onClick={() => {
                          setRunTarget(item.dataset)
                          setRunDialogOpen(true)
                        }}
                      >
                        <Play className="h-3 w-3" />
                        Run
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* RAG Quality bar chart */}
      {results.length > 0 && (
        <section className="grid gap-3">
          <h2 className="text-sm font-semibold">RAG Quality by Dataset</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={results} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="dataset" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
              <Tooltip
                formatter={(v) => (typeof v === "number" ? v.toFixed(3) : (v ?? "—"))}
              />
              <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
              <ReferenceLine
                y={0.6}
                stroke="#6366f1"
                strokeDasharray="4 4"
                label={{ value: "HR@5 0.60", position: "insideTopRight", fontSize: 9 }}
              />
              {METRIC_BARS.map((m) => (
                <Bar key={m.key} dataKey={m.key} name={m.label} fill={m.color} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </section>
      )}

      {/* HR@5 Over Time sparkline */}
      <section className="grid gap-3">
        <h2 className="text-sm font-semibold">Retrieval Quality Over Time</h2>
        <p className="text-xs text-muted-foreground">
          HR@5 per dataset across all eval runs. Dashed line = 0.60 threshold.
        </p>
        {historyQuery.isLoading ? (
          <Skeleton className="h-48 w-full" />
        ) : historyQuery.isError ? (
          <div className="rounded-md border border-destructive/30 p-3 text-sm text-destructive">
            Failed to load history.
          </div>
        ) : history.length === 0 ? (
          <div className="flex min-h-32 flex-col items-center justify-center gap-2 rounded-md border border-dashed text-center">
            <div className="text-xs text-muted-foreground">No eval history yet.</div>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={sparklineData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="run"
                tick={{ fontSize: 10 }}
                label={{ value: "Run", position: "insideBottomRight", offset: -4, fontSize: 10 }}
              />
              <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} />
              <Tooltip
                formatter={(v, name) =>
                  typeof v === "number" ? [v.toFixed(3), name ?? ""] : [(v ?? "—"), name ?? ""]
                }
              />
              <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
              <ReferenceLine
                y={0.6}
                stroke="#6366f1"
                strokeDasharray="4 4"
                label={{ value: "0.60", position: "insideTopRight", fontSize: 9 }}
              />
              {sparklineDatasets.map((ds) => (
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
        )}
      </section>

      <RunEvalDialog
        open={runDialogOpen}
        onOpenChange={setRunDialogOpen}
        submitting={runMutation.isPending}
        onSubmit={(payload) => runMutation.mutate(payload)}
      />
    </div>
  )
}
