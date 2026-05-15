import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { EvalRunFull, EvalRunSummary } from "./types"

function fmt(value: number | null | undefined): string {
  if (value == null) return "n/a"
  return value.toFixed(3)
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
            <TableHead>Model</TableHead>
            <TableHead>HR@5</TableHead>
            <TableHead>MRR</TableHead>
            <TableHead>Faith</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((run) => (
            <TableRow key={run.id || `${run.run_at}-${run.model_used}`}>
              <TableCell className="whitespace-nowrap text-xs">
                {new Date(run.run_at).toLocaleString()}
              </TableCell>
              <TableCell className="max-w-36 truncate text-xs">{run.model_used}</TableCell>
              <TableCell>{fmt(run.hit_rate_5)}</TableCell>
              <TableCell>{fmt(run.mrr)}</TableCell>
              <TableCell>{fmt(run.faithfulness)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
