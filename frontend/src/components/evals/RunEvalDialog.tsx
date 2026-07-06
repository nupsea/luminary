import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { AlertTriangle, Play } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { fetchEvalModels, isExternalJudge, judgeOptionsFrom } from "./api"

interface RunEvalDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (payload: {
    judge_model: string
    check_citations: boolean
    max_questions: number
    rerank: boolean
    ablation: boolean
  }) => void
  submitting: boolean
}

export function RunEvalDialog({ open, onOpenChange, onSubmit, submitting }: RunEvalDialogProps) {
  const modelsQuery = useQuery({
    queryKey: ["eval-models"],
    queryFn: fetchEvalModels,
    enabled: open,
    staleTime: 60_000,
  })
  const judgeOptions = judgeOptionsFrom(modelsQuery.data, "None — fast HR@5/MRR (no judge)")
  const [mode, setMode] = useState<"single" | "ablation">("single")
  const [rerank, setRerank] = useState(false)
  const [judgeModel, setJudgeModel] = useState("")
  const [checkCitations, setCheckCitations] = useState(false)
  const [maxQuestions, setMaxQuestions] = useState(20)
  const external = isExternalJudge(judgeModel)
  const ablation = mode === "ablation"

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Run Eval</DialogTitle>
          <DialogDescription>Score this dataset against the current retrieval and QA pipeline.</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <label className="grid gap-1 text-sm">
            <span className="font-medium">Mode</span>
            <select
              className="h-9 rounded-md border bg-background px-3 text-sm"
              value={mode}
              onChange={(event) => setMode(event.target.value as "single" | "ablation")}
            >
              <option value="single">Single run</option>
              <option value="ablation">Strategy ablation (vector/fts/graph/rrf/+rerank)</option>
            </select>
          </label>

          {!ablation && (
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={rerank}
                onChange={(event) => setRerank(event.target.checked)}
              />
              Cross-encoder reranker
            </label>
          )}

          <label className="grid gap-1 text-sm">
            <span className="font-medium">Judge Model{ablation ? " — not used in ablation" : ""}</span>
            <select
              className="h-9 rounded-md border bg-background px-3 text-sm disabled:opacity-50"
              value={ablation ? "" : judgeModel}
              disabled={ablation}
              onChange={(event) => setJudgeModel(event.target.value)}
            >
              {judgeOptions.map((opt) => (
                <option key={opt.value || "disabled"} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            {modelsQuery.isLoading && (
              <span className="text-xs text-muted-foreground">Loading available models…</span>
            )}
          </label>

          {external && (
            <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
              <AlertTriangle className="h-4 w-4" />
              This will send chunks to an external API.
            </div>
          )}

          {judgeModel === "" ? (
            <div className="flex items-center gap-2 rounded-md border border-muted bg-muted/40 p-2 text-xs text-muted-foreground">
              <AlertTriangle className="h-4 w-4" />
              Faithfulness, answer-relevance, and citation grounding will be skipped without a judge model.
            </div>
          ) : (
            <div className="rounded-md border border-muted bg-muted/40 p-2 text-xs text-muted-foreground">
              Answers are generated live by the app QA pipeline (its default model), then scored
              by the judge. Slower than retrieval-only, but measures the real product.
            </div>
          )}

          {!ablation && (
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={checkCitations}
                onChange={(event) => setCheckCitations(event.target.checked)}
              />
              Check citations
            </label>
          )}

          <label className="grid gap-1 text-sm">
            <span className="font-medium">Max Questions: {maxQuestions}</span>
            <input
              type="range"
              min={5}
              max={100}
              step={5}
              value={maxQuestions}
              onChange={(event) => setMaxQuestions(Number(event.target.value))}
            />
          </label>
        </div>

        <DialogFooter>
          <button
            type="button"
            className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-50"
            disabled={submitting}
            onClick={() =>
              onSubmit({
                judge_model: ablation ? "" : judgeModel,
                check_citations: ablation ? false : checkCitations,
                max_questions: maxQuestions,
                rerank: ablation ? false : rerank,
                ablation,
              })
            }
          >
            <Play className="h-4 w-4" />
            Run
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
