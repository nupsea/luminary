import { useQuery } from "@tanstack/react-query"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet } from "@/lib/apiClient"
import type { EvalRunFull } from "./types"

const fetchAblationRuns = (): Promise<EvalRunFull[]> =>
  apiGet<EvalRunFull[]>("/evals/runs", { eval_kind: "ablation", limit: 200 })

const STRATEGIES = ["vector", "fts", "graph", "rrf"] as const

export function AblationsTab() {
  const query = useQuery({
    queryKey: ["eval-runs-ablation"],
    queryFn: fetchAblationRuns,
    staleTime: 30_000,
  })

  if (query.isLoading) {
    return (
      <div className="grid gap-2">
        {[0, 1].map((i) => (
          <Skeleton key={i} className="h-40 w-full" />
        ))}
      </div>
    )
  }

  if (query.isError) {
    return (
      <div className="rounded-md border border-destructive/30 p-3 text-sm text-destructive">
        Failed to load ablation results.
      </div>
    )
  }

  const runs = (query.data ?? []).filter((r) => r.ablation_metrics != null)

  if (runs.length === 0) {
    return (
      <div className="flex min-h-40 flex-col items-center justify-center gap-2 rounded-md border border-dashed text-center">
        <div className="text-sm font-medium">No ablation results yet</div>
        <div className="text-xs text-muted-foreground">
          Run an ablation eval to populate this view.
        </div>
      </div>
    )
  }

  // Latest run per dataset
  const latestPerDataset = new Map<string, EvalRunFull>()
  for (const run of runs) {
    if (!latestPerDataset.has(run.dataset_name)) {
      latestPerDataset.set(run.dataset_name, run)
    }
  }

  const chartData = Array.from(latestPerDataset.entries()).map(([dataset, run]) => {
    const metrics = run.ablation_metrics as Record<string, { hit_rate_5?: number }>
    const row: Record<string, string | number> = { dataset }
    for (const strategy of STRATEGIES) {
      row[strategy] = metrics[strategy]?.hit_rate_5 ?? 0
    }
    return row
  })

  const COLORS = {
    vector: "#6366f1",
    fts: "#f59e0b",
    graph: "#10b981",
    rrf: "#3b82f6",
  }

  return (
    <div className="grid gap-4">
      <p className="text-sm text-muted-foreground">
        HR@5 by retrieval strategy, latest run per dataset.
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="dataset" tick={{ fontSize: 11 }} />
          <YAxis tickFormatter={(v: number) => `${Math.round(v * 100)}%`} tick={{ fontSize: 11 }} />
          <Tooltip
            formatter={(value) =>
              typeof value === "number" ? `${Math.round(value * 100)}%` : String(value ?? "")
            }
          />
          <Legend />
          {STRATEGIES.map((strategy) => (
            <Bar key={strategy} dataKey={strategy} fill={COLORS[strategy]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
