import { useQuery } from "@tanstack/react-query"
import { Skeleton } from "@/components/ui/skeleton"
import { API_BASE } from "@/lib/config"
import type { EvalRegressionItem } from "./types"

async function fetchRegressions(): Promise<EvalRegressionItem[]> {
  const res = await fetch(`${API_BASE}/monitoring/evals/regressions`)
  if (!res.ok) throw new Error("Failed to fetch regressions")
  return res.json() as Promise<EvalRegressionItem[]>
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`
}

function dropPct(v: number): string {
  return `-${Math.round(v * 100)}%`
}

export function RegressionsTab() {
  const query = useQuery({
    queryKey: ["eval-regressions"],
    queryFn: fetchRegressions,
    staleTime: 30_000,
  })

  if (query.isLoading) {
    return (
      <div className="grid gap-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  if (query.isError) {
    return (
      <div className="rounded-md border border-destructive/30 p-3 text-sm text-destructive">
        Failed to load regression data.
      </div>
    )
  }

  const regressions = query.data ?? []

  if (regressions.length === 0) {
    return (
      <div className="flex min-h-40 flex-col items-center justify-center gap-2 rounded-md border border-dashed text-center">
        <div className="text-sm font-medium">No regressions detected</div>
        <div className="text-xs text-muted-foreground">
          Regression detection requires at least 5 runs per dataset. No significant drops found.
        </div>
      </div>
    )
  }

  return (
    <div className="grid gap-4">
      <p className="text-sm text-muted-foreground">
        Metrics that dropped more than 5% versus the moving baseline (window=5).
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="py-2 pr-4 text-xs font-medium">Dataset</th>
              <th className="py-2 pr-4 text-xs font-medium">Metric</th>
              <th className="py-2 pr-4 text-xs font-medium">Baseline</th>
              <th className="py-2 pr-4 text-xs font-medium">Current</th>
              <th className="py-2 pr-4 text-xs font-medium">Drop</th>
            </tr>
          </thead>
          <tbody>
            {regressions.map((r, i) => (
              <tr key={i} className="border-b last:border-0">
                <td className="py-2 pr-4 text-xs">{r.dataset}</td>
                <td className="py-2 pr-4 text-xs text-muted-foreground">{r.metric}</td>
                <td className="py-2 pr-4 text-xs">{pct(r.baseline_value)}</td>
                <td className="py-2 pr-4 text-xs">{pct(r.current_value)}</td>
                <td className="py-2 pr-4 text-xs font-semibold text-destructive">
                  {dropPct(r.drop_pct)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
