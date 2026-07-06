import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"
import { metricColor, shippedAblationArm, THRESHOLDS } from "./thresholds"
import type { EvalRunFull, EvalRunSummary } from "./types"

function fmt(value: number | null | undefined): string {
  if (value == null) return "—"
  return value.toFixed(3)
}

// Ablation runs keep their scores per strategy arm; show the shipped arm so
// the row carries real numbers instead of dashes. ndcg_10 lives in
// extra_metrics on single runs (no dedicated DB column).
function rowScores(run: EvalRunSummary | EvalRunFull) {
  if (run.status === "failed") {
    return { hr5: null, mrr: null, ndcg: null, kind: "failed" }
  }
  if ("ablation_metrics" in run && run.eval_kind === "ablation") {
    const shipped = shippedAblationArm(run as EvalRunFull)
    if (shipped) {
      return {
        hr5: shipped.arm.hit_rate_5,
        mrr: shipped.arm.mrr,
        ndcg: shipped.arm.ndcg_10 ?? null,
        kind: `ablation · ${shipped.label}`,
      }
    }
  }
  const rawNdcg = "extra_metrics" in run ? run.extra_metrics?.ndcg_10 : null
  return {
    hr5: run.hit_rate_5,
    mrr: run.mrr,
    ndcg: typeof rawNdcg === "number" ? rawNdcg : null,
    kind: run.eval_kind ?? "—",
  }
}

export function ScoresTable({ runs }: { runs: Array<EvalRunSummary | EvalRunFull> }) {
  if (runs.length === 0) {
    return <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">No runs yet.</div>
  }

  return (
    <div className="overflow-hidden rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Date</TableHead>
            <TableHead>Kind</TableHead>
            <TableHead>Model</TableHead>
            <TableHead>HR@5</TableHead>
            <TableHead>MRR@5</TableHead>
            <TableHead>nDCG@10</TableHead>
            <TableHead>Faith</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((run) => {
            const s = rowScores(run)
            return (
              <TableRow key={run.id || `${run.run_at}-${run.model_used}`}>
                <TableCell className="whitespace-nowrap text-xs">
                  {new Date(run.run_at).toLocaleString()}
                </TableCell>
                <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                  {s.kind}
                </TableCell>
                <TableCell className="max-w-36 truncate text-xs">{run.model_used}</TableCell>
                <TableCell className={cn(metricColor(s.hr5, THRESHOLDS.hit_rate_5))}>
                  {fmt(s.hr5)}
                </TableCell>
                <TableCell className={cn(metricColor(s.mrr, THRESHOLDS.mrr))}>
                  {fmt(s.mrr)}
                </TableCell>
                <TableCell className={cn(metricColor(s.ndcg, THRESHOLDS.ndcg_10))}>
                  {fmt(s.ndcg)}
                </TableCell>
                <TableCell className={cn(metricColor(run.faithfulness, THRESHOLDS.faithfulness))}>
                  {fmt(run.faithfulness)}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
