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
import { apiGet } from "@/lib/apiClient"

// "" = no judge (retrieval-only). Live models are fetched so the dropdown only
// offers judges that are actually pulled/configured — a hardcoded list drifts
// from what Ollama has and produces "model not pulled" failures on Run.
const fetchModels = () => apiGet<{ local: string[]; frontier: string[] }>("/evals/models")

interface RunEvalDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (payload: { judge_model: string; check_citations: boolean; max_questions: number }) => void
  submitting: boolean
}

export function RunEvalDialog({ open, onOpenChange, onSubmit, submitting }: RunEvalDialogProps) {
  const modelsQuery = useQuery({
    queryKey: ["eval-models"],
    queryFn: fetchModels,
    enabled: open,
    staleTime: 60_000,
  })
  const judgeOptions = [
    { value: "", label: "None — fast HR@5/MRR (no judge)" },
    ...(modelsQuery.data?.local ?? []).map((m) => ({ value: m, label: `Local: ${m}` })),
    ...(modelsQuery.data?.frontier ?? []).map((m) => ({ value: m, label: `Frontier: ${m}` })),
  ]
  const [judgeModel, setJudgeModel] = useState("")
  const [checkCitations, setCheckCitations] = useState(false)
  const [maxQuestions, setMaxQuestions] = useState(20)
  const external = /^(openai|anthropic|gemini)\//.test(judgeModel)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Run Eval</DialogTitle>
          <DialogDescription>Score this dataset against the current retrieval and QA pipeline.</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <label className="grid gap-1 text-sm">
            <span className="font-medium">Judge Model</span>
            <select
              className="h-9 rounded-md border bg-background px-3 text-sm"
              value={judgeModel}
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

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={checkCitations}
              onChange={(event) => setCheckCitations(event.target.checked)}
            />
            Check citations
          </label>

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
            onClick={() => onSubmit({ judge_model: judgeModel, check_citations: checkCitations, max_questions: maxQuestions })}
          >
            <Play className="h-4 w-4" />
            Run
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
