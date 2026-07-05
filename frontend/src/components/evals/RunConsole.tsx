import { useMemo, useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { Play } from "lucide-react"
import { toast } from "sonner"
import { API_BASE } from "@/lib/config"
import { apiGet } from "@/lib/apiClient"
import { cn } from "@/lib/utils"
import { errorFromResponse, toSelection, type DatasetSelection } from "./api"
import type { GoldenDataset } from "./types"

// Live model list so the judge dropdown only offers judges that are actually
// pulled/configured — a hardcoded list drifts from Ollama and fails on Run.
const fetchModels = () => apiGet<{ local: string[]; frontier: string[] }>("/evals/models")

type Mode = "single" | "ablation"

interface RunConsoleProps {
  datasets: GoldenDataset[]
  value: DatasetSelection | null
  onChange: (selection: DatasetSelection | null) => void
  running: boolean
  runningLabel: string | null
  onStarted: (label: string) => void
}

export function RunConsole({
  datasets,
  value,
  onChange,
  running,
  runningLabel,
  onStarted,
}: RunConsoleProps) {
  // Every runnable dataset, generated and file-backed alike — one console
  // runs them all with the same options.
  const options = useMemo(() => {
    const generated = datasets
      .filter((d) => d.source === "db" && d.status === "complete" && d.id)
      .map((d) => toSelection(d))
      .filter((s): s is DatasetSelection => s !== null)
    const files = datasets
      .filter((d) => d.source === "file")
      .map((d) => toSelection(d))
      .filter((s): s is DatasetSelection => s !== null)
    return { generated, files, all: [...generated, ...files] }
  }, [datasets])

  const [mode, setMode] = useState<Mode>("single")
  const [rerank, setRerank] = useState(false)
  const [judgeModel, setJudgeModel] = useState("")
  const [maxQuestions, setMaxQuestions] = useState(50)

  const modelsQuery = useQuery({
    queryKey: ["eval-models"],
    queryFn: fetchModels,
    staleTime: 60_000,
  })
  const judgeOptions = [
    { value: "", label: "None — fast retrieval metrics" },
    ...(modelsQuery.data?.local ?? []).map((m) => ({ value: m, label: `Local: ${m}` })),
    ...(modelsQuery.data?.frontier ?? []).map((m) => ({ value: m, label: `Frontier: ${m}` })),
  ]

  const selection = value ?? options.all[0] ?? null
  const external = /^(openai|anthropic|gemini)\//.test(judgeModel)

  const runMutation = useMutation({
    mutationFn: async () => {
      if (!selection) throw new Error("Pick a dataset first")
      const payload = {
        judge_model: mode === "ablation" ? "" : judgeModel,
        rerank: mode === "single" ? rerank : false,
        ablation: mode === "ablation",
        max_questions: maxQuestions,
      }
      const res =
        selection.source === "db"
          ? await fetch(`${API_BASE}/evals/datasets/${selection.key}/run`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ ...payload, check_citations: false }),
            })
          : await fetch(`${API_BASE}/evals/run`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ ...payload, dataset: selection.key }),
            })
      if (!res.ok) throw await errorFromResponse(res, "Failed to start eval")
      return res.json()
    },
    onSuccess: () => {
      const cfg =
        mode === "ablation"
          ? "strategy ablation"
          : rerank
            ? "rerank on"
            : "rerank off"
      const judge = judgeModel && mode === "single" ? ` · judge ${judgeModel.split("/").pop()}` : " · no judge"
      onStarted(`${selection?.name ?? ""} · ${cfg}${judge}`)
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
            value={selection ? `${selection.source}:${selection.key}` : ""}
            onChange={(e) => {
              const next = options.all.find(
                (s) => `${s.source}:${s.key}` === e.target.value,
              )
              onChange(next ?? null)
            }}
          >
            {options.all.length === 0 && <option value="">No datasets</option>}
            {options.generated.length > 0 && (
              <optgroup label="Generated datasets">
                {options.generated.map((s) => (
                  <option key={`${s.source}:${s.key}`} value={`${s.source}:${s.key}`}>
                    {s.name}
                  </option>
                ))}
              </optgroup>
            )}
            {options.files.length > 0 && (
              <optgroup label="File goldens">
                {options.files.map((s) => (
                  <option key={`${s.source}:${s.key}`} value={`${s.source}:${s.key}`}>
                    {s.name}
                  </option>
                ))}
              </optgroup>
            )}
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
            {judgeOptions.map((m) => (
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
          disabled={runMutation.isPending || !selection}
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
