import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, FlaskConical, Loader2, Play, X } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Progress } from "@/components/ui/progress"
import {
  estimateSeconds,
  expandTasks,
  formatDuration,
  formatMetric,
  mutatingStages,
  progressPct,
  rowsByTier,
  verdict,
} from "@/lib/modelLab"
import {
  type LabRun,
  cancelLabRun,
  fetchLabCatalogue,
  fetchLabRuns,
  startLabRun,
} from "@/lib/modelLabApi"

const TONE_CLASS = {
  good: "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  warn: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200",
  bad: "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200",
}

function Notice({ tone, children }: { tone: keyof typeof TONE_CLASS; children: React.ReactNode }) {
  return <div className={`rounded border p-2 text-[11px] ${TONE_CLASS[tone]}`}>{children}</div>
}

function RunTable({ run }: { run: LabRun }) {
  const groups = rowsByTier(run.rows)
  if (groups.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No metrics yet. They appear as each stage finishes.
      </p>
    )
  }
  return (
    <div className="space-y-4">
      {groups.map((group) => (
        <div key={group.tier}>
          <p className="text-xs font-medium text-foreground">{group.heading}</p>
          <p className="mb-1 max-w-3xl text-[11px] text-muted-foreground">{group.note}</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-1.5 pr-3 font-medium">metric</th>
                  {run.models.map((m) => (
                    <th key={m} className="py-1.5 pr-3 text-right font-medium">
                      {m}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {group.rows.map((row) => (
                  <tr key={row.key} className="border-b last:border-0">
                    <td className="py-1.5 pr-3 font-medium">
                      {row.key}
                      {row.identical && run.models.length > 1 ? (
                        <span
                          className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-800
                            dark:bg-amber-950 dark:text-amber-300"
                          title="Identical on every model — this metric did not measure the model."
                        >
                          did not move
                        </span>
                      ) : null}
                    </td>
                    {run.models.map((m) => (
                      <td key={m} className="py-1.5 pr-3 text-right tabular-nums">
                        {formatMetric(row.metric, row.values[m] ?? null)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  )
}

function RunCard({ run }: { run: LabRun }) {
  const v = verdict(run)
  const failed = run.arms.flatMap((a) => a.failed_tasks.map((t) => `${a.model} ${t}`))
  return (
    <div className="space-y-3 rounded-lg border border-border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-foreground">{run.models.join("  vs  ")}</p>
          <p className="text-[11px] text-muted-foreground">
            {new Date(run.started_at).toLocaleString()} · {run.tasks.join(", ")}
          </p>
        </div>
        <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
          {run.status}
        </span>
      </div>

      {run.status === "running" && (
        <div>
          <Progress value={progressPct(run)} />
          <p className="mt-1 text-[11px] text-muted-foreground">
            {run.completed_units} of {run.total_units} stage-runs finished
          </p>
        </div>
      )}

      <Notice tone={v.tone}>{v.text}</Notice>

      {run.restore_error && (
        <Notice tone="bad">
          The model you had selected could not be restored ({run.restore_error}). This app is now
          serving a model you did not choose — set it back in Settings.
        </Notice>
      )}
      {failed.length > 0 && (
        <Notice tone="warn">
          Excluded from the comparison because they did not finish: {failed.join(", ")}. A partial
          pass is not evidence.
        </Notice>
      )}
      {run.separation?.unmeasured_tasks?.length ? (
        <Notice tone="warn">
          Every metric matched on: {run.separation.unmeasured_tasks.join(", ")}. Two models do not
          score the same to full precision on work that depends on them, so that stage measured
          something other than the model.
        </Notice>
      ) : null}

      <RunTable run={run} />
    </div>
  )
}

/**
 * Compare models across the Luminary workflow, on demand.
 *
 * A run owns the model selection for its whole duration and some stages write
 * generated content into the library, so the form says so before you start and
 * the page keeps polling until the model is handed back.
 */
export function ModelLab() {
  const queryClient = useQueryClient()
  const [models, setModels] = useState<string[]>([])
  const [stages, setStages] = useState<string[]>(["intent"])
  const [qaDatasets, setQaDatasets] = useState<string[]>([])
  const [maxQuestions, setMaxQuestions] = useState(20)

  const catalogue = useQuery({
    queryKey: ["model-lab", "catalogue"],
    queryFn: fetchLabCatalogue,
    refetchInterval: 10_000,
  })

  const runs = useQuery({
    queryKey: ["model-lab", "runs"],
    queryFn: fetchLabRuns,
    // Poll while anything is in flight; a stage can take twenty minutes and a
    // page that stops updating is indistinguishable from one that broke.
    refetchInterval: (q) =>
      (q.state.data ?? []).some((r) => r.status === "running") ? 5_000 : false,
  })

  const start = useMutation({
    mutationFn: startLabRun,
    onSuccess: () => {
      toast.success("Comparison started")
      void queryClient.invalidateQueries({ queryKey: ["model-lab"] })
    },
    onError: (err: unknown) => {
      toast.error(err instanceof Error ? err.message : "Could not start the comparison")
    },
  })

  const cancel = useMutation({
    mutationFn: cancelLabRun,
    onSuccess: () => {
      toast.message("Stopping after the stage in flight")
      void queryClient.invalidateQueries({ queryKey: ["model-lab"] })
    },
  })

  if (catalogue.isLoading) {
    return (
      <div className="space-y-2" aria-busy="true">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-8 animate-pulse rounded bg-muted" />
        ))}
      </div>
    )
  }

  if (catalogue.isError || !catalogue.data) {
    return (
      <Notice tone="bad">
        Could not load the model lab:{" "}
        {catalogue.error instanceof Error ? catalogue.error.message : "unknown error"}
      </Notice>
    )
  }

  const cat = catalogue.data
  const tasks = expandTasks(stages, qaDatasets)
  const seconds = estimateSeconds(cat.tasks, stages, qaDatasets, models.length, maxQuestions)
  const willWrite = mutatingStages(cat.tasks, stages)
  const busy = cat.busy || start.isPending
  const runList = runs.data ?? []
  const active = runList.find((r) => r.status === "running")

  const toggle = (list: string[], value: string, set: (v: string[]) => void) =>
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value])

  return (
    <div className="space-y-6">
      <div className="space-y-3 rounded-lg border border-border p-4">
        <div className="flex items-center gap-2">
          <FlaskConical size={16} className="text-primary" />
          <h3 className="text-sm font-medium text-foreground">Compare models</h3>
        </div>
        <p className="max-w-3xl text-xs text-muted-foreground">
          Runs the workflow stages against each model in turn and reports the structural tier — the
          only metrics allowed to decide a swap. Judged scores are shown but never gate, and
          retrieval metrics are excluded because they have no generation-model term in them.
        </p>

        <div>
          <p className="mb-1 text-xs font-medium text-foreground">Models</p>
          <div className="flex flex-wrap gap-1.5">
            {cat.installed_models.map((m) => (
              <button
                key={m}
                onClick={() => toggle(models, m, setModels)}
                className={`rounded border px-2 py-1 text-[11px] transition-colors ${
                  models.includes(m)
                    ? "border-primary bg-primary/10 text-foreground"
                    : "border-border text-muted-foreground hover:bg-accent"
                }`}
              >
                {m.replace("ollama/", "")}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-1 text-xs font-medium text-foreground">Stages</p>
          <div className="flex flex-wrap gap-1.5">
            {[...cat.tasks.map((t) => ({ key: t.key, label: t.label })), { key: "qa", label: "Answering" }].map(
              (t) => (
                <button
                  key={t.key}
                  onClick={() => toggle(stages, t.key, setStages)}
                  className={`rounded border px-2 py-1 text-[11px] transition-colors ${
                    stages.includes(t.key)
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-border text-muted-foreground hover:bg-accent"
                  }`}
                >
                  {t.label}
                </button>
              ),
            )}
          </div>
        </div>

        {stages.includes("qa") && (
          <div>
            <p className="mb-1 text-xs font-medium text-foreground">
              Answering datasets — one run each, so a model bad at contracts and fine at prose shows
              as exactly that
            </p>
            <div className="flex flex-wrap gap-1.5">
              {cat.qa_datasets.map((d) => (
                <button
                  key={d}
                  onClick={() => toggle(qaDatasets, d, setQaDatasets)}
                  className={`rounded border px-2 py-1 text-[11px] transition-colors ${
                    qaDatasets.includes(d)
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-border text-muted-foreground hover:bg-accent"
                  }`}
                >
                  {d}
                </button>
              ))}
            </div>
            <label className="mt-2 flex items-center gap-2 text-[11px] text-muted-foreground">
              Questions per dataset
              <input
                type="number"
                min={0}
                max={500}
                value={maxQuestions}
                onChange={(e) => setMaxQuestions(Number(e.target.value))}
                className="w-20 rounded border border-border bg-background px-2 py-1 text-foreground"
              />
              <span>0 = every row</span>
            </label>
          </div>
        )}

        {willWrite.length > 0 && (
          <Notice tone="warn">
            {willWrite.join(" and ")} generate content into your library, and the whole run changes
            the selected model until it finishes (currently {cat.current_model}). It is put back at
            the end.
          </Notice>
        )}

        {models.length === 1 && (
          <Notice tone="warn">
            One model measures a baseline; it does not compare anything. Pick a second to get a
            verdict.
          </Notice>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() =>
              start.mutate({ models, tasks, qa_datasets: qaDatasets, max_questions: maxQuestions })
            }
            disabled={busy || models.length === 0 || tasks.length === 0}
            className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm
              font-medium text-primary-foreground transition-colors hover:bg-primary/90
              disabled:opacity-50"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {cat.busy ? "A comparison is running" : "Start comparison"}
          </button>
          {tasks.length > 0 && models.length > 0 && (
            <span className="text-[11px] text-muted-foreground">
              {models.length} model(s) × {tasks.length} stage(s) — roughly{" "}
              {formatDuration(seconds)}
            </span>
          )}
          {active && (
            <button
              onClick={() => cancel.mutate(active.id)}
              className="flex items-center gap-1 rounded-md border border-border px-3 py-1.5
                text-sm text-foreground transition-colors hover:bg-accent"
            >
              <X size={14} />
              Stop after this stage
            </button>
          )}
        </div>
      </div>

      {runList.length === 0 ? (
        <div className="rounded border border-dashed p-6 text-center text-xs text-muted-foreground">
          <AlertTriangle size={16} className="mx-auto mb-2 opacity-50" />
          No comparisons yet. Pick two models and a stage above.
        </div>
      ) : (
        <div className="space-y-4">
          {runList.map((run) => (
            <RunCard key={run.id} run={run} />
          ))}
        </div>
      )}
    </div>
  )
}
