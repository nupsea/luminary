import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BarChart3, Plus, RefreshCw } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { AblationsTab } from "@/components/evals/AblationsTab"
import { ResultsTab } from "@/components/evals/ResultsTab"
import { DatasetDetail } from "@/components/evals/DatasetDetail"
import { GenerateDatasetDialog } from "@/components/evals/GenerateDatasetDialog"
import { RegressionsTab } from "@/components/evals/RegressionsTab"
import { RoutingTab } from "@/components/evals/RoutingTab"
import { RunEvalDialog } from "@/components/evals/RunEvalDialog"
import { RunsTab } from "@/components/evals/RunsTab"
import type {
  DatasetSize,
  DocumentOption,
  EvalRunFull,
  EvalRunSummary,
  FileQuestion,
  GoldenDataset,
  GoldenDatasetDetail,
} from "@/components/evals/types"

type AnyRun = EvalRunSummary | EvalRunFull
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { apiDelete, apiGet, apiPost } from "@/lib/apiClient"

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

const fetchDatasets = (): Promise<GoldenDataset[]> =>
  apiGet<GoldenDataset[]>("/evals/datasets")

const fetchDataset = (id: string): Promise<GoldenDatasetDetail> =>
  apiGet<GoldenDatasetDetail>(`/evals/datasets/${id}`, { limit: 50 })

const fetchDatasetRuns = (id: string): Promise<EvalRunSummary[]> =>
  apiGet<EvalRunSummary[]>(`/evals/datasets/${id}/runs`)

const fetchGoldenFile = (
  name: string,
): Promise<{
  name: string
  total: number
  questions: FileQuestion[]
  offset: number
  limit: number
}> =>
  apiGet(`/evals/golden/${name}`, { limit: 50 })

const fetchFileRuns = (name: string): Promise<EvalRunFull[]> =>
  apiGet<EvalRunFull[]>("/evals/runs", { dataset_name: name, limit: 50 })

const USABLE_STAGES = new Set(["embedding", "entity_extract", "indexing", "complete"])

async function fetchDocuments(): Promise<DocumentOption[]> {
  const data = await apiGet<{ items: DocumentOption[] }>("/documents", {
    sort: "newest",
    page: 1,
    page_size: 100,
  })
  return data.items.filter((doc) => USABLE_STAGES.has(doc.stage))
}

// ---------------------------------------------------------------------------
// Tab nav types
// ---------------------------------------------------------------------------

type TabId = "datasets" | "results" | "runs" | "routing" | "ablations" | "regressions"
const TABS: { id: TabId; label: string }[] = [
  { id: "datasets", label: "Datasets" },
  { id: "results", label: "Results" },
  { id: "runs", label: "Runs" },
  { id: "routing", label: "Routing" },
  { id: "ablations", label: "Ablations" },
  { id: "regressions", label: "Regressions" },
]

function pct(v: number): string {
  return `${Math.round(v * 100)}%`
}

function metricColor(v: number | null | undefined, threshold: number): string {
  if (v == null) return ""
  if (v >= threshold) return "font-semibold text-green-700 dark:text-green-400"
  if (v >= threshold * 0.75) return "font-semibold text-amber-600 dark:text-amber-400"
  return "text-muted-foreground"
}

function getInitialTab(): TabId {
  const hash = window.location.hash.replace("#", "") as TabId
  return TABS.some((t) => t.id === hash) ? hash : "datasets"
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function Quality() {
  const qc = useQueryClient()
  const [activeTab, setActiveTab] = useState<TabId>(getInitialTab)
  const [generateOpen, setGenerateOpen] = useState(false)
  const [runOpen, setRunOpen] = useState(false)
  // db-backed selection
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // file-backed selection
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null)
  // eval in-flight tracking
  const [evalRunning, setEvalRunning] = useState(false)
  const evalTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function markEvalRunning() {
    setEvalRunning(true)
    if (evalTimerRef.current) clearTimeout(evalTimerRef.current)
    // auto-clear after 15 minutes in case the run silently fails
    evalTimerRef.current = setTimeout(() => setEvalRunning(false), 15 * 60 * 1000)
  }

  // Re-attach to in-flight runs on page mount (survives browser refresh) and
  // surface failures the user would otherwise never see.
  const seenFailuresRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const rows = await apiGet<Array<{
          key: string
          run_id: string
          status: "running" | "failed" | "done"
          error: string | null
          finished_at: number | null
        }>>("/evals/in-flight")
        if (cancelled) return
        const anyRunning = rows.some((r) => r.status === "running")
        if (anyRunning) markEvalRunning()
        else if (!evalRunning) setEvalRunning(false)
        for (const row of rows) {
          if (row.status === "failed" && !seenFailuresRef.current.has(row.run_id)) {
            seenFailuresRef.current.add(row.run_id)
            toast.error(`Eval failed for ${row.key}: ${row.error ?? "unknown error"}`)
          }
          if (row.status === "done" && row.finished_at) {
            // refresh the runs queries when something just completed
            void qc.invalidateQueries({ queryKey: ["eval-dataset-runs", row.key] })
            void qc.invalidateQueries({ queryKey: ["eval-file-runs", row.key] })
          }
        }
      } catch {
        // ignore — polling is best-effort
      }
    }
    void poll()
    const id = setInterval(poll, 5000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleTabChange(tab: TabId) {
    setActiveTab(tab)
    window.location.hash = tab
  }

  // Datasets query
  const datasetsQuery = useQuery({
    queryKey: ["eval-datasets"],
    queryFn: fetchDatasets,
    refetchInterval: (query) => {
      const data = query.state.data as GoldenDataset[] | undefined
      return data?.some((d) => d.status === "generating" || d.status === "pending") ? 5000 : false
    },
  })

  const documentsQuery = useQuery({
    queryKey: ["eval-documents"],
    queryFn: fetchDocuments,
  })

  // DB-backed dataset detail
  const detailQuery = useQuery({
    queryKey: ["eval-dataset", selectedId],
    queryFn: () => fetchDataset(selectedId as string),
    enabled: Boolean(selectedId),
    refetchInterval: (query) => {
      const data = query.state.data as GoldenDatasetDetail | undefined
      return data?.status === "generating" || data?.status === "pending" ? 5000 : false
    },
  })

  const runsQuery = useQuery({
    queryKey: ["eval-dataset-runs", selectedId],
    queryFn: () => fetchDatasetRuns(selectedId as string),
    enabled: Boolean(selectedId),
  })

  // File-backed dataset detail
  const goldenFileQuery = useQuery({
    queryKey: ["eval-golden-file", selectedFileName],
    queryFn: () => fetchGoldenFile(selectedFileName as string),
    enabled: Boolean(selectedFileName),
    staleTime: 30_000,
  })

  const fileRunsQuery = useQuery({
    queryKey: ["eval-file-runs", selectedFileName],
    queryFn: () => fetchFileRuns(selectedFileName as string),
    enabled: Boolean(selectedFileName),
    staleTime: 30_000,
  })

  // Mutations
  const createMutation = useMutation({
    mutationFn: (payload: {
      name: string
      size: DatasetSize
      document_ids: string[]
      generator_model?: string
      question_count?: number
    }) => apiPost<{ id: string; status: string }>("/evals/datasets", payload),
    onSuccess: (data) => {
      setGenerateOpen(false)
      setSelectedId(data.id)
      void qc.invalidateQueries({ queryKey: ["eval-datasets"] })
      toast.success("Dataset generation started")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Create failed"),
  })

  const runMutation = useMutation({
    mutationFn: (payload: {
      judge_model: string
      check_citations: boolean
      max_questions: number
    }) => {
      if (selectedFileName) {
        // File-backed: POST /evals/run
        return apiPost("/evals/run", {
          dataset: selectedFileName,
          judge_model: payload.judge_model || null,
          check_citations: payload.check_citations,
          max_questions: payload.max_questions,
        })
      }
      // DB-backed: POST /evals/datasets/{id}/run
      return apiPost(`/evals/datasets/${selectedId}/run`, payload)
    },
    onSuccess: () => {
      setRunOpen(false)
      markEvalRunning()
      if (activeTab !== "runs") setActiveTab("runs")
      if (selectedId) void qc.invalidateQueries({ queryKey: ["eval-dataset-runs", selectedId] })
      if (selectedFileName)
        void qc.invalidateQueries({ queryKey: ["eval-file-runs", selectedFileName] })
      toast.success("Eval started — switching to Runs tab")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Run failed"),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/evals/datasets/${id}`),
    onSuccess: () => {
      setSelectedId(null)
      void qc.invalidateQueries({ queryKey: ["eval-datasets"] })
      toast.success("Dataset deleted")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Delete failed"),
  })

  // All datasets merged and sorted: most recent activity first
  const allDatasets = useMemo(() => {
    const all = datasetsQuery.data ?? []
    return [...all].sort((a, b) => {
      const aKey = a.last_run?.run_at ?? a.completed_at ?? a.created_at ?? ""
      const bKey = b.last_run?.run_at ?? b.completed_at ?? b.created_at ?? ""
      return bKey.localeCompare(aKey)
    })
  }, [datasetsQuery.data])

  const isDetailOpen = Boolean(selectedId) || Boolean(selectedFileName)
  const detailSource = selectedFileName ? "file" : "db"

  // For file-backed detail, synthesise a minimal GoldenDatasetDetail
  const fileDetail: GoldenDatasetDetail | undefined = selectedFileName
    ? {
        id: null,
        name: selectedFileName,
        description: null,
        size: null,
        generator_model: null,
        source_document_ids: [],
        status: "complete",
        generated_count: goldenFileQuery.data?.total ?? 0,
        target_count: goldenFileQuery.data?.total ?? 0,
        created_at: null,
        completed_at: null,
        error_message: null,
        last_run: null,
        source: "file",
        questions: [],
        offset: 0,
        limit: 50,
      }
    : undefined

  return (
    <div className="flex h-full flex-col overflow-hidden bg-background">
      {evalRunning && (
        <div className="flex shrink-0 items-center justify-between border-b border-amber-200 bg-amber-50 px-6 py-2 text-xs text-amber-800">
          <div className="flex items-center gap-2">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500" />
            Eval running in background — results will appear in the Runs tab when complete
          </div>
          <button
            type="button"
            className="text-amber-600 underline hover:text-amber-800"
            onClick={() => setEvalRunning(false)}
          >
            Dismiss
          </button>
        </div>
      )}
      <header className="flex shrink-0 items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">Quality</h1>
          <p className="text-sm text-muted-foreground">Evaluate and track quality across datasets.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm font-medium hover:bg-accent"
            onClick={() => void datasetsQuery.refetch()}
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          <button
            type="button"
            className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground"
            onClick={() => setGenerateOpen(true)}
          >
            <Plus className="h-4 w-4" />
            Generate Dataset
          </button>
        </div>
      </header>

      {/* Tab navigation */}
      <div className="flex shrink-0 items-center gap-1 border-b px-6">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => handleTabChange(tab.id)}
            className={cn(
              "inline-flex h-10 items-center border-b-2 px-3 text-sm font-medium transition-colors",
              activeTab === tab.id
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <main className="min-h-0 flex-1 overflow-auto p-6">
        {/* Datasets tab */}
        {activeTab === "datasets" && (
          <>
            {datasetsQuery.isLoading ? (
              <div className="grid gap-2">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-11 w-full" />
                ))}
              </div>
            ) : datasetsQuery.isError ? (
              <div className="rounded-md border border-destructive/30 p-4 text-sm text-destructive">
                Datasets unavailable.
              </div>
            ) : allDatasets.length === 0 ? (
              <div className="flex min-h-96 flex-col items-center justify-center gap-3 rounded-md border border-dashed text-center">
                <BarChart3 className="h-8 w-8 text-muted-foreground" />
                <div className="text-sm font-medium">No evaluation datasets yet</div>
                <button
                  type="button"
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground"
                  onClick={() => setGenerateOpen(true)}
                >
                  <Plus className="h-4 w-4" />
                  Generate Dataset
                </button>
              </div>
            ) : (
              <div className="overflow-x-auto rounded-md border">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b bg-muted/40 text-left text-muted-foreground">
                      <th className="py-2 pl-3 pr-3 font-medium">Name</th>
                      <th className="py-2 pr-3 font-medium">Source</th>
                      <th className="py-2 pr-3 font-medium">Questions</th>
                      <th className="py-2 pr-3 font-medium">Generated</th>
                      <th className="py-2 pr-3 font-medium">Last Run</th>
                      <th className="py-2 pr-3 text-right font-medium">HR@5</th>
                      <th className="py-2 pr-3 text-right font-medium">MRR</th>
                      <th className="py-2 pr-3 text-right font-medium" title="Requires judge model">Faith</th>
                    </tr>
                  </thead>
                  <tbody>
                    {allDatasets.map((dataset) => {
                      const isSelected =
                        dataset.source === "db"
                          ? dataset.id === selectedId
                          : dataset.name === selectedFileName
                      const lr = dataset.last_run
                      return (
                        <tr
                          key={dataset.id ?? dataset.name}
                          onClick={() => {
                            if (dataset.source === "db") {
                              setSelectedFileName(null)
                              setSelectedId(dataset.id)
                            } else {
                              setSelectedId(null)
                              setSelectedFileName(dataset.name)
                            }
                          }}
                          className={cn(
                            "cursor-pointer border-b last:border-0 hover:bg-accent/50",
                            isSelected && "bg-primary/5",
                          )}
                        >
                          <td className="py-2.5 pl-3 pr-3">
                            <span className="font-medium text-foreground">{dataset.name}</span>
                            {dataset.status === "generating" || dataset.status === "pending" ? (
                              <span className="ml-2 text-muted-foreground">
                                {dataset.generated_count}/{dataset.target_count}
                              </span>
                            ) : null}
                          </td>
                          <td className="py-2.5 pr-3 text-muted-foreground">
                            {dataset.source === "file" ? "file" : "generated"}
                          </td>
                          <td className="py-2.5 pr-3 text-muted-foreground">
                            {dataset.source === "file" ? "—" : dataset.generated_count}
                          </td>
                          <td className="py-2.5 pr-3 text-muted-foreground">
                            {dataset.created_at
                              ? new Date(dataset.created_at).toLocaleDateString()
                              : "—"}
                          </td>
                          <td className="py-2.5 pr-3 text-muted-foreground">
                            {lr?.run_at ? new Date(lr.run_at).toLocaleString() : "never"}
                          </td>
                          <td className={cn("py-2.5 pr-3 text-right", metricColor(lr?.hit_rate_5, 0.6))}>
                            {lr?.hit_rate_5 != null ? pct(lr.hit_rate_5) : "—"}
                          </td>
                          <td className={cn("py-2.5 pr-3 text-right", metricColor(lr?.mrr, 0.45))}>
                            {lr?.mrr != null ? pct(lr.mrr) : "—"}
                          </td>
                          <td className={cn("py-2.5 pr-3 text-right", metricColor(lr?.faithfulness, 0.65))}>
                            {lr?.faithfulness != null ? pct(lr.faithfulness) : (
                              <span className="text-muted-foreground/50" title="Run with a judge model to compute faithfulness">—</span>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {activeTab === "results" && (
          <ResultsTab onRunStarted={markEvalRunning} />
        )}
        {activeTab === "runs" && <RunsTab polling={evalRunning} />}
        {activeTab === "routing" && <RoutingTab />}
        {activeTab === "ablations" && <AblationsTab />}
        {activeTab === "regressions" && <RegressionsTab />}
      </main>

      <GenerateDatasetDialog
        open={generateOpen}
        documents={documentsQuery.data || []}
        loadingDocuments={documentsQuery.isLoading}
        onOpenChange={setGenerateOpen}
        submitting={createMutation.isPending}
        onSubmit={(payload) => createMutation.mutate(payload)}
      />

      <DatasetDetail
        open={isDetailOpen}
        detail={selectedFileName ? fileDetail : detailQuery.data}
        runs={(selectedFileName ? (fileRunsQuery.data ?? []) : (runsQuery.data ?? [])) as AnyRun[]}
        loading={selectedFileName ? false : detailQuery.isLoading}
        loadingFile={goldenFileQuery.isLoading}
        fileQuestions={goldenFileQuery.data?.questions}
        fileTotal={goldenFileQuery.data?.total}
        source={detailSource}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedId(null)
            setSelectedFileName(null)
          }
        }}
        onRun={() => setRunOpen(true)}
        deleting={deleteMutation.isPending}
        onDelete={() => {
          if (!selectedId) return
          if (window.confirm("Delete this evaluation dataset?")) {
            deleteMutation.mutate(selectedId)
          }
        }}
      />

      <RunEvalDialog
        open={runOpen}
        onOpenChange={setRunOpen}
        submitting={runMutation.isPending}
        onSubmit={(payload) => runMutation.mutate(payload)}
      />
    </div>
  )
}
