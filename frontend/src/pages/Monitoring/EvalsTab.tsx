// Evals tab: consolidates the four eval surfaces that previously
// stacked on one scroll -- latest-run bar chart, HR@5 history, metric
// trends, RAGAS results with run trigger, and the raw runs table.

import { EvalTrendsPanel } from "@/components/EvalTrendsPanel"

import { EvalHistorySparkline, RAGQualityChart, RetrievalFunnelChart } from "./Charts"
import { EvalPanel } from "./EvalPanel"
import { EmptyState, SectionErrorCard, SectionSkeleton } from "./SharedUI"
import { fetchEvalHistory, fetchEvalRuns } from "./api"
import type { EvalHistoryItem, EvalRun } from "./types"
import { useSection } from "./useSection"

export function EvalsTab() {
  const evalRuns = useSection<EvalRun[]>("Eval Runs", fetchEvalRuns, [])
  const evalHist = useSection<EvalHistoryItem[]>("Eval History", fetchEvalHistory, [])

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">RAG Quality</h2>
        <p className="text-xs text-muted-foreground">Latest run per dataset.</p>
        {evalRuns.loading ? (
          <SectionSkeleton rows={4} />
        ) : evalRuns.error ? (
          <SectionErrorCard name="RAG Quality" />
        ) : (
          <RAGQualityChart evalRuns={evalRuns.data} />
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Retrieval Funnel</h2>
        <p className="text-xs text-muted-foreground">
          L1 pool recall is what candidate generation hands the reranker; the fused and
          reranked bars are the top-5 cut. A tall recall bar over a short rerank bar means
          the ceiling is L2 (the cross-encoder), not L1. Latest ablation run per dataset.
        </p>
        {evalRuns.loading ? (
          <SectionSkeleton rows={4} />
        ) : evalRuns.error ? (
          <SectionErrorCard name="Retrieval Funnel" />
        ) : (
          <RetrievalFunnelChart evalRuns={evalRuns.data} />
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Retrieval Quality Over Time</h2>
        <p className="text-xs text-muted-foreground">
          HR@5 per dataset across eval runs. Dashed line = 0.60 threshold.
        </p>
        {evalHist.loading ? (
          <SectionSkeleton rows={3} />
        ) : evalHist.error ? (
          <SectionErrorCard name="Retrieval Quality Over Time" />
        ) : (
          <EvalHistorySparkline history={evalHist.data} />
        )}
      </section>

      <section className="flex flex-col gap-3">
        {evalHist.loading ? (
          <SectionSkeleton rows={3} />
        ) : evalHist.error ? (
          <SectionErrorCard name="Eval Trends" />
        ) : (
          <EvalTrendsPanel history={evalHist.data} />
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">RAGAS Eval Results</h2>
        <p className="text-xs text-muted-foreground">
          Latest result per dataset. Green = meets threshold, amber = close, grey = below. Click
          Run Eval to trigger a background eval run.
        </p>
        <EvalPanel />
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Eval Runs</h2>
        {evalRuns.loading ? (
          <SectionSkeleton rows={4} />
        ) : evalRuns.error ? (
          <SectionErrorCard name="Eval Runs" />
        ) : evalRuns.data.length === 0 ? (
          <EmptyState message="No evaluation runs yet. Run evals/run_eval.py to populate." />
        ) : (
          <div className="overflow-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/50">
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Dataset</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Run At</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">HR@5</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">MRR</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">Faithfulness</th>
                </tr>
              </thead>
              <tbody>
                {evalRuns.data.map((run) => {
                  const hr5 = run.hit_rate_5
                  const rowBg =
                    hr5 != null && hr5 < 0.5
                      ? "bg-red-50 dark:bg-red-950/30"
                      : hr5 != null && hr5 > 0.7
                        ? "bg-green-50 dark:bg-green-950/30"
                        : ""
                  return (
                    <tr key={run.id} className={`border-b border-border last:border-0 ${rowBg}`}>
                      <td className="px-4 py-2 font-medium text-foreground">{run.dataset_name}</td>
                      <td className="px-4 py-2 text-xs text-muted-foreground">
                        {new Date(run.run_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-2 text-right text-foreground">
                        {hr5 != null ? hr5.toFixed(2) : "—"}
                      </td>
                      <td className="px-4 py-2 text-right text-foreground">
                        {run.mrr != null ? run.mrr.toFixed(2) : "—"}
                      </td>
                      <td className="px-4 py-2 text-right text-foreground">
                        {run.faithfulness != null ? run.faithfulness.toFixed(2) : "—"}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
