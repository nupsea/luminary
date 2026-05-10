// EvalPanel -- RAGAS eval results table fetched from /evals/results
// with threshold-based score colouring. Lets the user re-run an eval
// for a chosen dataset.

import { useEffect, useState } from "react"
import { toast } from "sonner"

import { logger } from "@/lib/logger"

import { fetchEvalDatasets, fetchEvalResults, triggerEvalRun } from "./api"
import {
  EmptyState,
  SectionErrorCard,
  SectionSkeleton,
} from "./SharedUI"
import type { EvalResultItem, SectionState } from "./types"
import { initSection } from "./types"
import { scoreColor } from "./utils"

export function EvalPanel() {
  const [state, setState] = useState<SectionState<EvalResultItem[]>>(initSection([]))
  const [datasetsState, setDatasetsState] = useState<SectionState<string[]>>(initSection([]))
  const [runningDatasets, setRunningDatasets] = useState<Set<string>>(new Set())
  const [selectedDataset, setSelectedDataset] = useState<string>("")

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

    fetchEvalDatasets()
      .then((d) => {
        if (!cancelled) {
          setDatasetsState({ loading: false, data: d, error: false })
          if (d.length > 0) setSelectedDataset(d[0])
        }
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] EvalDatasets fetch failed", e)
        if (!cancelled) setDatasetsState({ loading: false, data: [], error: true })
      })

    return () => {
      cancelled = true
    }
  }, [])

  function handleRunEval(dataset: string) {
    if (!dataset) return
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

  if (state.loading || datasetsState.loading) {
    return <SectionSkeleton rows={3} />
  }
  if (state.error) {
    return <SectionErrorCard name="RAGAS Eval Results" />
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <select
          value={selectedDataset}
          onChange={(e) => setSelectedDataset(e.target.value)}
          className="rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        >
          {datasetsState.data.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
          {datasetsState.data.length === 0 && (
            <option value="" disabled>
              No datasets found
            </option>
          )}
        </select>
        <button
          onClick={() => handleRunEval(selectedDataset)}
          disabled={!selectedDataset || runningDatasets.has(selectedDataset)}
          className="rounded px-3 py-1 text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
        >
          {runningDatasets.has(selectedDataset) ? "Starting..." : "Run New Eval"}
        </button>
      </div>

      {state.data.length === 0 ? (
        <EmptyState message="No eval results yet. Run an eval above to populate." />
      ) : (
        <div className="overflow-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-secondary/50">
                <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">
                  Dataset
                </th>
                <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">
                  Run At
                </th>
                <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">
                  HR@5
                </th>
                <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">
                  MRR
                </th>
                <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">
                  Faithfulness
                </th>
                <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">
                  Ctx Precision
                </th>
                <th className="px-4 py-2 text-center text-xs font-semibold text-muted-foreground">
                  Action
                </th>
              </tr>
            </thead>
            <tbody>
              {state.data.map((item) => (
                <tr key={item.dataset} className="border-b border-border last:border-0">
                  <td className="px-4 py-2 font-medium text-foreground">{item.dataset}</td>
                  <td className="px-4 py-2 text-xs text-muted-foreground">
                    {item.run_at ? new Date(item.run_at).toLocaleString() : "—"}
                  </td>
                  <td
                    className={`px-4 py-2 text-right ${scoreColor(item.hit_rate_5, "hit_rate_5")}`}
                  >
                    {item.hit_rate_5 !== null ? item.hit_rate_5.toFixed(3) : "—"}
                  </td>
                  <td className={`px-4 py-2 text-right ${scoreColor(item.mrr, "mrr")}`}>
                    {item.mrr !== null ? item.mrr.toFixed(3) : "—"}
                  </td>
                  <td
                    className={`px-4 py-2 text-right ${scoreColor(item.faithfulness, "faithfulness")}`}
                  >
                    {item.faithfulness !== null ? item.faithfulness.toFixed(3) : "—"}
                  </td>
                  <td
                    className={`px-4 py-2 text-right ${scoreColor(item.context_precision, "context_precision")}`}
                  >
                    {item.context_precision !== null
                      ? item.context_precision.toFixed(3)
                      : "—"}
                  </td>
                  <td className="px-4 py-2 text-center">
                    <button
                      onClick={() => handleRunEval(item.dataset)}
                      disabled={runningDatasets.has(item.dataset)}
                      className="rounded px-2 py-1 text-xs font-medium bg-secondary text-secondary-foreground hover:bg-secondary/80 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
                    >
                      {runningDatasets.has(item.dataset) ? "Starting..." : "Run Again"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
