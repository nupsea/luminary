import { useMemo, useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { Play } from "lucide-react"
import { toast } from "sonner"
import { API_BASE } from "@/lib/config"
import { cn } from "@/lib/utils"
import {
  errorFromResponse,
  fetchEvalModels,
  isExternalJudge,
  judgeOptionsFrom,
  toSelection,
  type DatasetSelection,
} from "./api"
import type { GoldenDataset } from "./types"

type Mode = "retrieval" | "generation" | "ablation"

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
  // Every dataset, generated and file-backed alike — one console runs them
  // all with the same options. Datasets still generating stay visible but
  // disabled so a selected-but-unrunnable row reads as "not ready" instead
  // of a blank select.
  const options = useMemo(() => {
    const generated = datasets
      .filter((d) => d.source === "db" && d.id)
      .map((d) => ({ sel: toSelection(d), runnable: d.status === "complete" }))
      .filter((o): o is { sel: DatasetSelection; runnable: boolean } => o.sel !== null)
    const files = datasets
      .filter((d) => d.source === "file")
      .map((d) => ({ sel: toSelection(d), runnable: true }))
      .filter((o): o is { sel: DatasetSelection; runnable: boolean } => o.sel !== null)
    return { generated, files, all: [...generated, ...files] }
  }, [datasets])

  const [mode, setMode] = useState<Mode>("retrieval")
  const [rerank, setRerank] = useState(false)
  const [judgeModel, setJudgeModel] = useState("")
  const [maxQuestions, setMaxQuestions] = useState(50)

  const generation = mode === "generation"
  const ablation = mode === "ablation"

  const modelsQuery = useQuery({
    queryKey: ["eval-models"],
    queryFn: fetchEvalModels,
    staleTime: 60_000,
  })
  const judgeOptions = judgeOptionsFrom(modelsQuery.data, "None — faithfulness only (no judge)")

  const fallback = options.all.find((o) => o.runnable) ?? options.all[0] ?? null
  const selected = value
    ? (options.all.find((o) => o.sel.source === value.source && o.sel.key === value.key) ?? {
        sel: value,
        runnable: false,
      })
    : fallback
  const selection = selected?.sel ?? null
  const runnable = selected?.runnable ?? false
  const external = generation && isExternalJudge(judgeModel)

  const runMutation = useMutation({
    mutationFn: async () => {
      if (!selection) throw new Error("Pick a dataset first")
      const payload = {
        judge_model: generation ? judgeModel : "",
        rerank: ablation ? false : rerank,
        ablation,
        generate: generation,
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
      const cfg = ablation
        ? "strategy ablation"
        : generation
          ? `generation${rerank ? " · rerank on" : ""}`
          : `retrieval${rerank ? " · rerank on" : ""}`
      const judge =
        generation && judgeModel ? ` · judge ${judgeModel.split("/").pop()}` : ""
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
                (o) => `${o.sel.source}:${o.sel.key}` === e.target.value,
              )
              onChange(next?.sel ?? null)
            }}
          >
            {options.all.length === 0 && <option value="">No datasets</option>}
            {options.generated.length > 0 && (
              <optgroup label="Generated datasets">
                {options.generated.map(({ sel, runnable: ok }) => (
                  <option
                    key={`${sel.source}:${sel.key}`}
                    value={`${sel.source}:${sel.key}`}
                    disabled={!ok}
                  >
                    {sel.name}
                    {ok ? "" : " (generating…)"}
                  </option>
                ))}
              </optgroup>
            )}
            {options.files.length > 0 && (
              <optgroup label="File goldens">
                {options.files.map(({ sel }) => (
                  <option key={`${sel.source}:${sel.key}`} value={`${sel.source}:${sel.key}`}>
                    {sel.name}
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
            <option value="retrieval">Retrieval only — fast HR@5 / MRR</option>
            <option value="generation">Generation — answers + faithfulness</option>
            <option value="ablation">Strategy ablation (vector/fts/graph/rrf/+rerank)</option>
          </select>
        </label>

        <label className="grid gap-1 text-xs">
          <span
            className="font-medium text-muted-foreground"
            title="Optional. Faithfulness is scored without a judge; a judge adds answer relevance."
          >
            Judge (answer relevance){generation ? " — optional" : " — generation only"}
          </span>
          <select
            className="h-9 rounded-md border bg-background px-2 text-sm disabled:opacity-50"
            value={generation ? judgeModel : ""}
            disabled={!generation}
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

      {mode === "retrieval" && (
        <div className="mt-2 rounded-md border border-muted bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          Retrieval metrics only (HR@5 / MRR / nDCG). No answers are generated, so Faithfulness
          is not scored — switch Mode to Generation for that.
        </div>
      )}
      {generation && !judgeModel && (
        <div className="mt-2 rounded-md border border-muted bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          Answers are generated live by the app QA pipeline, then scored for Faithfulness by the
          local NLI model (HHEM) — deterministic, no LLM cost. Add a judge above for answer
          relevance. Expect roughly a minute per question locally; lower Max questions for a quick
          read.
        </div>
      )}
      {generation && judgeModel && (
        <div className="mt-2 rounded-md border border-muted bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          Judged run: every question gets a live /qa answer, scored for Faithfulness (HHEM) plus
          answer relevance by the judge. With local models expect roughly a minute per question —
          lower Max questions for a quick read.
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-4">
        {!ablation && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} />
            Cross-encoder reranker
          </label>
        )}
        {external && (
          <span className="text-xs text-amber-600">Sends chunks to an external API.</span>
        )}
        {selection && !runnable && (
          <span className="text-xs text-muted-foreground">
            {selection.name} is still generating — pick another dataset or wait.
          </span>
        )}
        <button
          type="button"
          disabled={runMutation.isPending || !selection || !runnable}
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
