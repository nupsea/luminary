import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet } from "@/lib/apiClient"
import { stripMarkdown } from "@/lib/utils"
import type { EvalRunFull } from "./types"

const fetchEvalRuns = (params: {
  dataset_name?: string
  eval_kind?: string
  model?: string
  limit: number
}): Promise<EvalRunFull[]> =>
  apiGet<EvalRunFull[]>("/evals/runs", {
    limit: params.limit,
    dataset_name: params.dataset_name,
    eval_kind: params.eval_kind,
    model: params.model,
  })

function pct(v: number | null | undefined): string {
  if (v == null) return "n/a"
  return `${Math.round(v * 100)}%`
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export function RunsTab({ polling = false }: { polling?: boolean }) {
  const [datasetFilter, setDatasetFilter] = useState("")
  const [kindFilter, setKindFilter] = useState("")
  const [modelFilter, setModelFilter] = useState("")
  const [limit, setLimit] = useState(50)

  const query = useQuery({
    queryKey: ["eval-runs", datasetFilter, kindFilter, modelFilter, limit],
    queryFn: () =>
      fetchEvalRuns({
        dataset_name: datasetFilter || undefined,
        eval_kind: kindFilter || undefined,
        model: modelFilter || undefined,
        limit,
      }),
    staleTime: polling ? 0 : 30_000,
    refetchInterval: polling ? 6_000 : false,
  })

  return (
    <div className="grid gap-4">
      {polling && (
        <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500" />
          Eval running in background — polling for results every 6s
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <input
          type="text"
          placeholder="Filter by dataset..."
          className="h-8 rounded-md border bg-background px-2 text-xs"
          value={datasetFilter}
          onChange={(e) => setDatasetFilter(e.target.value)}
        />
        <select
          className="h-8 rounded-md border bg-background px-2 text-xs"
          value={kindFilter}
          onChange={(e) => setKindFilter(e.target.value)}
        >
          <option value="">All kinds</option>
          <option value="retrieval">retrieval</option>
          <option value="routing">routing</option>
          <option value="ablation">ablation</option>
          <option value="faithfulness">faithfulness</option>
          <option value="generation">generation</option>
        </select>
        <input
          type="text"
          placeholder="Filter by model..."
          className="h-8 rounded-md border bg-background px-2 text-xs"
          value={modelFilter}
          onChange={(e) => setModelFilter(e.target.value)}
        />
        <select
          className="h-8 rounded-md border bg-background px-2 text-xs"
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
        >
          <option value={25}>25</option>
          <option value={50}>50</option>
          <option value={100}>100</option>
        </select>
      </div>

      {query.isLoading ? (
        <div className="grid gap-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : query.isError ? (
        <div className="rounded-md border border-destructive/30 p-3 text-sm text-destructive">
          Failed to load eval runs.
        </div>
      ) : !query.data || query.data.length === 0 ? (
        <div className="flex min-h-40 flex-col items-center justify-center gap-2 rounded-md border border-dashed text-center">
          <div className="text-sm font-medium">No eval runs yet</div>
          <div className="text-xs text-muted-foreground">Run an eval to populate this view.</div>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-3 font-medium">Dataset</th>
                <th className="py-2 pr-3 font-medium">Kind</th>
                <th className="py-2 pr-3 font-medium">Judge Model</th>
                <th className="py-2 pr-3 font-medium">Run At</th>
                <th className="py-2 pr-3 font-medium">HR@5</th>
                <th className="py-2 pr-3 font-medium">MRR</th>
                <th className="py-2 pr-3 font-medium">Faith</th>
                <th className="py-2 pr-3 font-medium">Routing</th>
              </tr>
            </thead>
            <tbody>
              {query.data.map((run) => (
                <tr key={run.id} className="border-b last:border-0">
                  <td className="py-2 pr-3">{stripMarkdown(run.dataset_name)}</td>
                  <td className="py-2 pr-3 text-muted-foreground">{run.eval_kind ?? "—"}</td>
                  <td className="py-2 pr-3 text-muted-foreground">{run.model_used}</td>
                  <td className="py-2 pr-3 text-muted-foreground">{fmtDate(run.run_at)}</td>
                  <td className="py-2 pr-3">{pct(run.hit_rate_5)}</td>
                  <td className="py-2 pr-3">{pct(run.mrr)}</td>
                  <td className="py-2 pr-3">{pct(run.faithfulness)}</td>
                  <td className="py-2 pr-3">{pct(run.routing_accuracy)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
