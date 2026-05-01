import { useState } from "react"
import { AlertTriangle, Play } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

const JUDGE_MODELS = ["ollama/gemma4", "ollama/mistral", "openai/gpt-4o-mini", ""]

interface RunEvalDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (payload: { judge_model: string; check_citations: boolean; max_questions: number }) => void
  submitting: boolean
}

export function RunEvalDialog({ open, onOpenChange, onSubmit, submitting }: RunEvalDialogProps) {
  const [judgeModel, setJudgeModel] = useState("ollama/gemma4")
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
              {JUDGE_MODELS.map((model) => (
                <option key={model || "disabled"} value={model}>
                  {model || "Disabled"}
                </option>
              ))}
            </select>
          </label>

          {external && (
            <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
              <AlertTriangle className="h-4 w-4" />
              This will send chunks to an external API.
            </div>
          )}

          {judgeModel === "" && (
            <div className="flex items-center gap-2 rounded-md border border-muted bg-muted/40 p-2 text-xs text-muted-foreground">
              <AlertTriangle className="h-4 w-4" />
              Faithfulness, answer-relevance, and citation grounding will be n/a without a judge model.
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
