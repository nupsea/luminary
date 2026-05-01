import { Play, Trash2 } from "lucide-react"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { stripMarkdown } from "@/lib/utils"
import { QuestionList } from "./QuestionList"
import { ScoresTable } from "./ScoresTable"
import type { EvalRunFull, EvalRunSummary, FileQuestion, GoldenDatasetDetail } from "./types"

interface DatasetDetailProps {
  open: boolean
  detail?: GoldenDatasetDetail
  runs: Array<EvalRunSummary | EvalRunFull>
  loading: boolean
  loadingFile?: boolean
  fileQuestions?: FileQuestion[]
  fileTotal?: number
  source?: "db" | "file"
  onOpenChange: (open: boolean) => void
  onRun: () => void
  onDelete: () => void
  deleting: boolean
}

function FileQuestionList({ questions }: { questions: FileQuestion[] }) {
  if (questions.length === 0) {
    return <div className="text-sm text-muted-foreground">No questions in this dataset.</div>
  }
  return (
    <ul className="divide-y text-sm">
      {questions.map((q, i) => (
        <li key={i} className="py-2">
          <div className="font-medium">{stripMarkdown(q.q)}</div>
          {q.context_hint && (
            <div className="mt-0.5 text-xs text-muted-foreground">{stripMarkdown(q.context_hint)}</div>
          )}
        </li>
      ))}
    </ul>
  )
}

export function DatasetDetail({
  open,
  detail,
  runs,
  loading,
  loadingFile,
  fileQuestions,
  fileTotal,
  source,
  onOpenChange,
  onRun,
  onDelete,
  deleting,
}: DatasetDetailProps) {
  const isFile = source === "file" || detail?.source === "file"

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col overflow-y-auto sm:max-w-3xl">
        <SheetHeader>
          <SheetTitle>{detail?.name || "Dataset"}</SheetTitle>
          <SheetDescription>
            {isFile
              ? `file-backed golden -- ${fileTotal ?? detail?.generated_count ?? 0} questions`
              : detail
                ? `${detail.generated_count}/${detail.target_count} questions · ${detail.generator_model}`
                : "Loading dataset"}
          </SheetDescription>
        </SheetHeader>

        {loading || !detail ? (
          <div className="grid gap-4">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        ) : (
          <div className="grid gap-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                <Badge variant={detail.status === "complete" ? "green" : "blue"}>{detail.status}</Badge>
                {detail.size && <Badge variant="gray">{detail.size}</Badge>}
                {!isFile && (
                  <Badge variant="indigo">{detail.source_document_ids.length} docs</Badge>
                )}
              </div>
              {!isFile && (
                <button
                  type="button"
                  className="inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm font-medium text-destructive hover:bg-destructive/10 disabled:opacity-50"
                  disabled={deleting}
                  onClick={onDelete}
                >
                  <Trash2 className="h-4 w-4" />
                  Delete
                </button>
              )}
              <button
                type="button"
                className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-50"
                disabled={!isFile && detail.status !== "complete"}
                onClick={onRun}
              >
                <Play className="h-4 w-4" />
                Run Eval
              </button>
            </div>

            <section className="grid gap-2">
              <h2 className="text-sm font-semibold">Questions</h2>
              {isFile ? (
                loadingFile ? (
                  <Skeleton className="h-32 w-full" />
                ) : (
                  <FileQuestionList questions={fileQuestions ?? []} />
                )
              ) : (
                <QuestionList questions={detail.questions} />
              )}
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
