import { Play, Trash2 } from "lucide-react"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Badge } from "@/components/ui/badge"
import { QuestionList } from "./QuestionList"
import { ScoresTable } from "./ScoresTable"
import type { EvalRunSummary, GoldenDatasetDetail } from "./types"

interface DatasetDetailProps {
  open: boolean
  detail?: GoldenDatasetDetail
  runs: EvalRunSummary[]
  loading: boolean
  onOpenChange: (open: boolean) => void
  onRun: () => void
  onDelete: () => void
  deleting: boolean
}

export function DatasetDetail({
  open,
  detail,
  runs,
  loading,
  onOpenChange,
  onRun,
  onDelete,
  deleting,
}: DatasetDetailProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col overflow-y-auto sm:max-w-3xl">
        <SheetHeader>
          <SheetTitle>{detail?.name || "Dataset"}</SheetTitle>
          <SheetDescription>
            {detail
              ? `${detail.generated_count}/${detail.target_count} questions · ${detail.generator_model}`
              : "Loading dataset"}
          </SheetDescription>
        </SheetHeader>

        {loading || !detail ? (
          <div className="text-sm text-muted-foreground">Loading...</div>
        ) : (
          <div className="grid gap-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                <Badge variant={detail.status === "complete" ? "green" : "blue"}>{detail.status}</Badge>
                {detail.size && <Badge variant="gray">{detail.size}</Badge>}
                <Badge variant="indigo">{detail.source_document_ids.length} docs</Badge>
              </div>
              <button
                type="button"
                className="inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm font-medium text-destructive hover:bg-destructive/10 disabled:opacity-50"
                disabled={deleting}
                onClick={onDelete}
              >
                <Trash2 className="h-4 w-4" />
                Delete
              </button>
              <button
                type="button"
                className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-50"
                disabled={detail.status !== "complete"}
                onClick={onRun}
              >
                <Play className="h-4 w-4" />
                Run Eval
              </button>
            </div>

            <section className="grid gap-2">
              <h2 className="text-sm font-semibold">Questions</h2>
              <QuestionList questions={detail.questions} />
            </section>

            <section className="grid gap-2">
              <h2 className="text-sm font-semibold">Past Runs</h2>
              <ScoresTable runs={runs} />
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
