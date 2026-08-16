import { useQuery } from "@tanstack/react-query"

import { apiGet } from "@/lib/apiClient"
import { buildModelMatrix, formatStructural } from "@/lib/modelMatrix"

import type { EvalRunFull } from "./types"

/**
 * One column per model, one row per structural metric.
 *
 * Judged scores are deliberately absent: a cross-model faithfulness delta is a
 * style artifact, and one was spent on a model decision here before. Retrieval
 * metrics are absent for a different reason — they have no generation-model
 * term at all, so putting them in this table lets corpus noise read as a model
 * difference.
 */
export function ModelMatrix() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["eval-runs", "model-matrix"],
    queryFn: () => apiGet<EvalRunFull[]>("/evals/runs", { limit: 200 }),
  })

  if (isLoading) {
    return (
      <div className="space-y-2" aria-busy="true">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="h-6 animate-pulse rounded bg-muted" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rounded border border-rose-300 bg-rose-50 p-3 text-xs text-rose-800
        dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200">
        Could not load eval runs: {error instanceof Error ? error.message : "unknown error"}
      </div>
    )
  }

  const matrix = buildModelMatrix(data ?? [])

  if (matrix.models.length === 0) {
    return (
      <div className="rounded border border-dashed p-6 text-center text-xs text-muted-foreground">
        No runs carry a resolved model yet. Run <code>make eval-matrix MODELS=a,b</code> and each
        model appears here as a column.
      </div>
    )
  }

  return (
    <div>
      <p className="mb-3 max-w-3xl text-xs text-muted-foreground">
        The structural tier only — what the model emitted before anything repaired it, how much of
        what was asked for arrived, and how much the deterministic card gate threw away. These are
        the numbers allowed to decide a model swap. Judged scores and retrieval metrics are not
        here: the first are style, the second have no model term in them.
      </p>

      {matrix.models.length === 1 && (
        <div className="mb-3 rounded border border-amber-300 bg-amber-50 p-2 text-[11px]
          text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Only one model has been measured, so there is nothing to compare yet.
        </div>
      )}

      {matrix.fingerprints.length > 1 && (
        <div className="mb-3 rounded border border-amber-300 bg-amber-50 p-2 text-[11px]
          text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          These columns were not all measured against the same corpus or funnel
          ({matrix.fingerprints.length} distinct provenances). Re-ingesting one document has moved
          an untouched document's score by as much as a model change did — read them as separate
          measurements, not as a ranking.
        </div>
      )}

      {matrix.identicalKeys.length > 0 && matrix.models.length > 1 && (
        <div className="mb-3 rounded border border-amber-300 bg-amber-50 p-2 text-[11px]
          text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Identical on every model: <code>{matrix.identicalKeys.join(", ")}</code>. Two models do
          not produce the same number to full precision on work that depends on them, so a metric
          that never moves measured something else — a stored artifact replayed, or a path the
          model switch never reached. It does not mean the models are equivalent.
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="py-1.5 pr-3 font-medium">metric</th>
              {matrix.models.map((model) => (
                <th key={model} className="py-1.5 pr-3 text-right font-medium">
                  {model}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.rows.map((row) => (
              <tr key={row.key} className="border-b last:border-0">
                <td className="py-1.5 pr-3 font-medium">
                  {row.key}
                  {row.identical && matrix.models.length > 1 ? (
                    <span
                      className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-800
                        dark:bg-amber-950 dark:text-amber-300"
                      title="Identical on every model — this metric did not measure the model."
                    >
                      did not move
                    </span>
                  ) : null}
                </td>
                {matrix.models.map((model) => (
                  <td key={model} className="py-1.5 pr-3 text-right tabular-nums">
                    {row.cells[model] == null
                      ? "—"
                      : formatStructural(row.metric, row.cells[model])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
