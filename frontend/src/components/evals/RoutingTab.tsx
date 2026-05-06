import { useQuery } from "@tanstack/react-query"
import { Skeleton } from "@/components/ui/skeleton"
import { API_BASE } from "@/lib/config"
import type { EvalRunFull } from "./types"

async function fetchRoutingRuns(): Promise<EvalRunFull[]> {
  const res = await fetch(`${API_BASE}/evals/runs?eval_kind=routing&limit=50`)
  if (!res.ok) throw new Error("Failed to fetch routing runs")
  return res.json() as Promise<EvalRunFull[]>
}

function pct(v: number | null | undefined): string {
  if (v == null) return "n/a"
  return `${Math.round(v * 100)}%`
}

export function RoutingTab() {
  const query = useQuery({
    queryKey: ["eval-runs-routing"],
    queryFn: fetchRoutingRuns,
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
        Failed to load routing results.
      </div>
    )
  }

  const runs = query.data ?? []
  const withPerRoute = runs.filter((r) => r.per_route != null)

  if (withPerRoute.length === 0) {
    return (
      <div className="flex min-h-40 flex-col items-center justify-center gap-2 rounded-md border border-dashed text-center">
        <div className="text-sm font-medium">No routing eval results yet</div>
        <div className="text-xs text-muted-foreground">
          Run a routing eval to populate this view.
        </div>
      </div>
    )
  }

  // Use most recent run with per_route data
  const latest = withPerRoute[0]
  // per_route is {route: {precision: number, recall: number}} from compute_per_route_precision_recall
  const perRoute = latest.per_route as Record<string, { precision?: number; recall?: number }>
  const routes = Object.keys(perRoute)

  return (
    <div className="grid gap-6">
      <div className="text-sm text-muted-foreground">
        Overall routing accuracy:{" "}
        <span className="font-medium text-foreground">{pct(latest.routing_accuracy)}</span>
        {" · "}dataset: <span className="font-medium text-foreground">{latest.dataset_name}</span>
      </div>

      <section className="grid gap-2">
        <h2 className="text-sm font-semibold">Per-Route Precision / Recall</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-1.5 pr-3 font-medium">Route</th>
                <th className="py-1.5 pr-3 font-medium">Precision</th>
                <th className="py-1.5 pr-3 font-medium">Recall</th>
                <th className="py-1.5 pr-3 font-medium">F1</th>
              </tr>
            </thead>
            <tbody>
              {routes.map((route) => {
                const { precision = 0, recall = 0 } = perRoute[route] ?? {}
                const f1 = precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : 0
                return (
                  <tr key={route} className="border-b last:border-0">
                    <td className="py-1.5 pr-3 font-medium">{route}</td>
                    <td className="py-1.5 pr-3">{pct(precision)}</td>
                    <td className="py-1.5 pr-3">{pct(recall)}</td>
                    <td className="py-1.5 pr-3">{pct(f1)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
