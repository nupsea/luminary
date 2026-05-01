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
  const perRoute = latest.per_route as Record<string, Record<string, number>>
  const intents = Object.keys(perRoute)
  const allPredicted = Array.from(
    new Set(intents.flatMap((intent) => Object.keys(perRoute[intent] ?? {})))
  )

  return (
    <div className="grid gap-6">
      <div className="text-sm text-muted-foreground">
        Overall routing accuracy:{" "}
        <span className="font-medium text-foreground">{pct(latest.routing_accuracy)}</span>
        {" · "}dataset: <span className="font-medium text-foreground">{latest.dataset_name}</span>
      </div>

      <section className="grid gap-2">
        <h2 className="text-sm font-semibold">Confusion Matrix</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-1.5 pr-3 font-medium">Actual \ Predicted</th>
                {allPredicted.map((p) => (
                  <th key={p} className="py-1.5 pr-3 font-medium">
                    {p}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {intents.map((intent) => {
                const row = perRoute[intent] ?? {}
                const total = Object.values(row).reduce((a, b) => a + b, 0)
                return (
                  <tr key={intent} className="border-b last:border-0">
                    <td className="py-1.5 pr-3 font-medium">{intent}</td>
                    {allPredicted.map((p) => {
                      const val = row[p] ?? 0
                      const isCorrect = p === intent
                      return (
                        <td
                          key={p}
                          className={`py-1.5 pr-3 ${isCorrect ? "font-semibold text-green-700" : "text-muted-foreground"}`}
                        >
                          {val}
                          {total > 0 && ` (${Math.round((val / total) * 100)}%)`}
                        </td>
                      )
                    })}
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
