import { useMemo, useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { Play } from "lucide-react"
import { toast } from "sonner"
import { API_BASE } from "@/lib/config"
import { cn } from "@/lib/utils"
import type { GoldenDataset } from "./types"

// "" = no judge (fast, retrieval-only). A judge generates real answers via the
// app's /qa pipeline and scores those. Frontier options are opt-in and warned.
const JUDGE_MODELS: { value: string; label: string }[] = [
  { value: "", label: "None — fast HR@5/MRR" },
  { value: "ollama/qwen2.5:14b-instruct", label: "Local: qwen2.5:14b" },
  { value: "ollama/mistral", label: "Local: mistral" },
  { value: "openai/gpt-4o-mini", label: "Frontier: gpt-4o-mini" },
]

type Mode = "single" | "ablation"

interface RunConsoleProps {
  datasets: GoldenDataset[]
  value: string
  onChange: (dataset: string) => void
  running: boolean
  runningLabel: string | null
  onStarted: (label: string) => void
}

async function fetchDatasets(): Promise<GoldenDataset[]> {
  const res = await fetch(`${API_BASE}/evals/datasets`)
  if (!res.ok) throw new Error("Failed to fetch datasets")
  return res.json() as Promise<GoldenDataset[]>
}

export function RunConsole({
  datasets,
  value,
  onChange,
  running,
  runningLabel,
  onStarted,
}: RunConsoleProps) {
  // file-backed datasets are the ones run_eval consumes via --dataset
  const fileDatasets = useMemo(
    () => datasets.filter((d) => d.source === "file").map((d) => d.name),
    [datasets],
  )
  const fallback = useQuery({
    queryKey: ["eval-datasets-console"],
    queryFn: fetchDatasets,
    enabled: datasets.length === 0,
  })
  const options = fileDatasets.length
    ? fileDatasets
    : (fallback.data ?? []).filter((d) => d.source === "file").map((d) => d.name)

  const [mode, setMode] = useState<Mode>("single")
  const [rerank, setRerank] = useState(false)
  const [judgeModel, setJudgeModel] = useState("")
  const [maxQuestions, setMaxQuestions] = useState(50)

  const effectiveDataset = value || options[0] || ""
  const external = /^(openai|anthropic|gemini)\//.test(judgeModel)

  const runMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE}/evals/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dataset: effectiveDataset,
          // ablation is retrieval-only — no judge; "" => no judge for single too
          judge_model: mode === "ablation" ? "" : judgeModel,
          rerank: mode === "single" ? rerank : false,
          ablation: mode === "ablation",
          max_questions: maxQuestions,
        }),
      })
      if (!res.ok) throw new Error("Failed to start eval")
      return res.json()
    },
    onSuccess: () => {
      const cfg =
        mode === "ablation"
          ? "strategy ablation"
          : rerank
            ? "rerank on"
            : "rerank off"
      const judge = judgeModel ? ` · judge ${judgeModel.split("/").pop()}` : " · no judge"
      onStarted(`${effectiveDataset} · ${cfg}${judge}`)
      toast.success("Eval started")
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Run failed"),
  })

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Run an evaluation</h2>
        {running && (
          <span className="inline-flex items-center gap-2 rounded-full bg-amber-50 px-2.5 py-1 text-xs text-amber-800">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500" />
            {runningLabel ?? "running…"}
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="grid gap-1 text-xs">
          <span className="font-medium text-muted-foreground">Dataset</span>
          <select
            className="h-9 rounded-md border bg-background px-2 text-sm"
            value={effectiveDataset}
            onChange={(e) => onChange(e.target.value)}
          >
            {options.length === 0 && <option value="">No datasets</option>}
            {options.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1 text-xs">
          <span className="font-medium text-muted-foreground">Mode</span>
          <select
            className="h-9 rounded-md border bg-background px-2 text-sm"
            value={mode}
            onChange={(e) => setMode(e.target.value as Mode)}
          >
            <option value="single">Single run</option>
            <option value="ablation">Strategy ablation (vector/fts/graph/rrf/+rerank)</option>
          </select>
        </label>

        <label className="grid gap-1 text-xs">
          <span
            className="font-medium text-muted-foreground"
            title="When set, answers are generated live by the app QA pipeline and scored by this judge"
          >
            Judge (generation){mode === "ablation" ? " — not used" : ""}
          </span>
          <select
            className="h-9 rounded-md border bg-background px-2 text-sm disabled:opacity-50"
            value={mode === "ablation" ? "" : judgeModel}
            disabled={mode === "ablation"}
            onChange={(e) => setJudgeModel(e.target.value)}
          >
            {JUDGE_MODELS.map((m) => (
              <option key={m.value || "none"} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1 text-xs">
          <span className="font-medium text-muted-foreground">Max questions: {maxQuestions}</span>
          <input
            type="range"
            min={5}
            max={100}
            step={5}
            value={maxQuestions}
            onChange={(e) => setMaxQuestions(Number(e.target.value))}
            className="h-9"
          />
        </label>
      </div>

      {mode === "ablation" && judgeModel && (
        <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Ablation is retrieval-only — your judge selection ({judgeModel.split("/").pop()}) will
          NOT be used and the run records no Faithfulness. Switch Mode to Single run to judge
          generated answers.
        </div>
      )}
      {mode === "single" && judgeModel && (
        <div className="mt-2 rounded-md border border-muted bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          Judged run: every question gets a live /qa answer, then the judge scores it. With
          local models expect roughly a minute per question — lower Max questions for a quick
          read.
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-4">
        {mode === "single" && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} />
            Cross-encoder reranker
          </label>
        )}
        {external && (
          <span className="text-xs text-amber-600">Sends chunks to an external API.</span>
        )}
        <button
          type="button"
          disabled={runMutation.isPending || !effectiveDataset}
          onClick={() => runMutation.mutate()}
          className={cn(
            "ml-auto inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground",
            "disabled:opacity-50",
          )}
        >
          <Play className="h-4 w-4" />
          Run
        </button>
      </div>
    </div>
  )
}
