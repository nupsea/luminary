import { useQuery } from "@tanstack/react-query"

import { apiGet } from "@/lib/apiClient"
import {
  type ComparableGroup,
  type KindRow,
  groupByComparability,
  isMixed,
  latestRetrievalPerDataset,
} from "@/lib/evalMatrix"

import type { EvalRunFull } from "./types"

function pct(v: number | null): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`
}

function scalar(v: number | boolean | string): string {
  if (typeof v === "boolean") return v ? "yes" : "no"
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4)
  return v
}

/** Colour the weakest kinds, so the spread reads without arithmetic. */
function band(v: number | null): string {
  if (v == null) return "text-muted-foreground"
  if (v >= 0.8) return "text-emerald-600 dark:text-emerald-400"
  if (v >= 0.6) return "text-amber-600 dark:text-amber-400"
  return "text-rose-600 dark:text-rose-400"
}

function Row({ row }: { row: KindRow }) {
  const env = row.environment
  return (
    <>
      <tr className="border-b last:border-0">
        <td className="py-1.5 pr-3 font-medium">{row.dataset}</td>
        <td className={`py-1.5 pr-3 text-right tabular-nums ${band(row.hitRate5)}`}>
          {pct(row.hitRate5)}
        </td>
        <td className="py-1.5 pr-3 text-right tabular-nums">{pct(row.mrr)}</td>
        <td className="py-1.5 pr-3 text-right tabular-nums">{pct(row.ndcg10)}</td>
        <td className="py-1.5 pr-3 text-right tabular-nums">
          {row.boundaryMisses == null ? "—" : row.boundaryMisses}
        </td>
        <td className="py-1.5 text-muted-foreground">
          {env?.self_judged ? (
            <span
              className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-800
                dark:bg-amber-950 dark:text-amber-300"
              title="One model wrote and graded this run; judged metrics are biased upward."
            >
              self-judged
            </span>
          ) : null}
          {env?.capture_error ? (
            <span className="text-[11px] text-rose-600" title={env.capture_error}>
              provenance unrecorded
            </span>
          ) : null}
        </td>
      </tr>
      {row.extras.length > 0 && (
        <tr className="border-b last:border-0">
          <td colSpan={6} className="pb-2 pl-3 text-[11px] text-muted-foreground">
            {row.extras.map(([key, value]) => (
              <span key={key} className="mr-3 inline-block">
                <span className="opacity-70">{key}</span> {scalar(value)}
              </span>
            ))}
          </td>
        </tr>
      )}
    </>
  )
}

function Group({ group, showLabel }: { group: ComparableGroup; showLabel: boolean }) {
  return (
    <div className="mb-6">
      {showLabel && (
        <div className="mb-1 text-[11px] text-muted-foreground">
          measured against {group.label}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-[11px] uppercase tracking-wide text-muted-foreground">
            <tr className="border-b">
              <th className="py-1.5 pr-3 text-left font-medium">Dataset</th>
              <th className="py-1.5 pr-3 text-right font-medium">HR@5</th>
              <th className="py-1.5 pr-3 text-right font-medium">MRR</th>
              <th className="py-1.5 pr-3 text-right font-medium">nDCG@10</th>
              <th className="py-1.5 pr-3 text-right font-medium">Split misses</th>
              <th className="py-1.5 text-left font-medium">Notes</th>
            </tr>
          </thead>
          <tbody>
            {group.rows.map((row) => (
              <Row key={row.runId} row={row} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/**
 * One row per kind of writing, worst first.
 *
 * Retrieval quality is a property of the document kind: on one funnel, measured
 * scores run from epistolary fiction to personal notes with everything else in
 * between. A single headline number hides which kind moved, and a table of rows
 * taken against different corpora hides that they cannot be compared at all --
 * so rows are grouped by what they were measured against.
 */
export function KindMatrix() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["eval-runs", "kind-matrix"],
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

  const rows = latestRetrievalPerDataset(data ?? [])
  if (rows.length === 0) {
    return (
      <div className="rounded border border-dashed p-6 text-center text-xs text-muted-foreground">
        No retrieval runs yet. Run <code>make eval</code> and they appear here, one row per kind.
      </div>
    )
  }

  const groups = groupByComparability(rows)
  const mixed = isMixed(groups)

  return (
    <div>
      <p className="mb-3 max-w-3xl text-xs text-muted-foreground">
        Latest run per dataset, weakest first. Each dataset is a different kind of writing against
        the same funnel, so the spread is what retrieval does to prose, tables, verse and dialogue
        — not one quality number for the product.
      </p>
      {mixed && (
        <div className="mb-3 rounded border border-amber-300 bg-amber-50 p-2 text-[11px]
          text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          These rows were not all measured against the same system. Re-ingesting one document has
          moved an untouched document's score by as much as a model change did, so rows are grouped
          by corpus and models; compare within a group, never across.
        </div>
      )}
      {groups.map((group) => (
        <Group key={group.fingerprint} group={group} showLabel={mixed || groups.length === 1} />
      ))}
    </div>
  )
}
