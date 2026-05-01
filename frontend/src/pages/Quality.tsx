import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BarChart3, Plus, RefreshCw } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import { AblationsTab } from "@/components/evals/AblationsTab"
import { DatasetCard } from "@/components/evals/DatasetCard"
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
import { API_BASE } from "@/lib/config"

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchDatasets(): Promise<GoldenDataset[]> {
  const res = await fetch(`${API_BASE}/evals/datasets`)
  if (!res.ok) throw new Error("Failed to fetch datasets")
  return res.json() as Promise<GoldenDataset[]>
}

async function fetchDataset(id: string): Promise<GoldenDatasetDetail> {
  const res = await fetch(`${API_BASE}/evals/datasets/${id}?limit=50`)
  if (!res.ok) throw new Error("Failed to fetch dataset")
  return res.json() as Promise<GoldenDatasetDetail>
}

async function fetchDatasetRuns(id: string): Promise<EvalRunSummary[]> {
  const res = await fetch(`${API_BASE}/evals/datasets/${id}/runs`)
  if (!res.ok) throw new Error("Failed to fetch dataset runs")
  return res.json() as Promise<EvalRunSummary[]>
}

async function fetchGoldenFile(
  name: string,
): Promise<{ name: string; total: number; questions: FileQuestion[]; offset: number; limit: number }> {
  const res = await fetch(`${API_BASE}/evals/golden/${name}?limit=50`)
  if (!res.ok) throw new Error("Failed to fetch golden file")
  return res.json() as Promise<{
    name: string
    total: number
    questions: FileQuestion[]
    offset: number
    limit: number
  }>
}

async function fetchFileRuns(name: string): Promise<EvalRunFull[]> {
  const res = await fetch(`${API_BASE}/evals/runs?dataset_name=${encodeURIComponent(name)}&limit=50`)
  if (!res.ok) throw new Error("Failed to fetch file runs")
  return res.json() as Promise<EvalRunFull[]>
}

async function fetchDocuments(): Promise<DocumentOption[]> {
  const params = new URLSearchParams({ sort: "newest", page: "1", page_size: "100" })
  const res = await fetch(`${API_BASE}/documents?${params.toString()}`)
  if (!res.ok) throw new Error("Failed to fetch documents")
  const data = (await res.json()) as { items: DocumentOption[] }
  return data.items.filter((doc) => doc.stage === "complete")
}

// ---------------------------------------------------------------------------
// Tab nav types
// ---------------------------------------------------------------------------

type TabId = "datasets" | "runs" | "routing" | "ablations" | "regressions"
const TABS: { id: TabId; label: string }[] = [
  { id: "datasets", label: "Datasets" },
  { id: "runs", label: "Runs" },
  { id: "routing", label: "Routing" },
  { id: "ablations", label: "Ablations" },
  { id: "regressions", label: "Regressions" },
]

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
    mutationFn: async (payload: {
      name: string
      size: DatasetSize
      document_ids: string[]
      generator_model?: string
    }) => {
      const res = await fetch(`${API_BASE}/evals/datasets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error("Failed to create dataset")
      return res.json() as Promise<{ id: string; status: string }>
    },
    onSuccess: (data) => {
      setGenerateOpen(false)
      setSelectedId(data.id)
      void qc.invalidateQueries({ queryKey: ["eval-datasets"] })
      toast.success("Dataset generation started")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Create failed"),
  })

  const runMutation = useMutation({
    mutationFn: async (payload: {
      judge_model: string
      check_citations: boolean
      max_questions: number
    }) => {
      if (selectedFileName) {
        // File-backed: POST /evals/run
        const res = await fetch(`${API_BASE}/evals/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            dataset: selectedFileName,
            judge_model: payload.judge_model || null,
            check_citations: payload.check_citations,
            max_questions: payload.max_questions,
          }),
        })
        if (!res.ok) throw new Error("Failed to start eval run")
        return res.json()
      }
      // DB-backed: POST /evals/datasets/{id}/run
      const res = await fetch(`${API_BASE}/evals/datasets/${selectedId}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error("Failed to start eval run")
      return res.json()
    },
    onSuccess: () => {
      setRunOpen(false)
      if (selectedId) void qc.invalidateQueries({ queryKey: ["eval-dataset-runs", selectedId] })
      if (selectedFileName)
        void qc.invalidateQueries({ queryKey: ["eval-file-runs", selectedFileName] })
      toast.success("Eval run started")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Run failed"),
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      const res = await fetch(`${API_BASE}/evals/datasets/${id}`, { method: "DELETE" })
      if (!res.ok) throw new Error("Failed to delete dataset")
    },
    onSuccess: () => {
      setSelectedId(null)
      void qc.invalidateQueries({ queryKey: ["eval-datasets"] })
      toast.success("Dataset deleted")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Delete failed"),
  })

  // Derived
  const dbDatasets = useMemo(
    () => (datasetsQuery.data || []).filter((d) => d.source === "db"),
    [datasetsQuery.data],
  )
  const fileDatasets = useMemo(
    () => (datasetsQuery.data || []).filter((d) => d.source === "file"),
    [datasetsQuery.data],
  )

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
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {[0, 1, 2].map((item) => (
                  <Skeleton key={item} className="h-44 w-full" />
                ))}
              </div>
            ) : datasetsQuery.isError ? (
              <div className="rounded-md border border-destructive/30 p-4 text-sm text-destructive">
                Datasets unavailable.
              </div>
            ) : dbDatasets.length === 0 && fileDatasets.length === 0 ? (
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
              <div className="grid gap-6">
                {dbDatasets.length > 0 && (
                  <section className="grid gap-3">
                    <h2 className="text-sm font-semibold">Generated Datasets</h2>
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                      {dbDatasets.map((dataset) => (
                        <DatasetCard
                          key={dataset.id || dataset.name}
                          dataset={dataset}
                          selected={dataset.id === selectedId}
                          onSelect={() => {
                            setSelectedFileName(null)
                            setSelectedId(dataset.id)
                          }}
                        />
                      ))}
                    </div>
                  </section>
                )}

                {fileDatasets.length > 0 && (
                  <section className="grid gap-3">
                    <h2 className="text-sm font-semibold">File Goldens</h2>
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                      {fileDatasets.map((dataset) => (
                        <DatasetCard
                          key={dataset.name}
                          dataset={dataset}
                          selected={dataset.name === selectedFileName}
                          onSelect={() => {
                            setSelectedId(null)
                            setSelectedFileName(dataset.name)
                          }}
                        />
                      ))}
                    </div>
                  </section>
                )}
              </div>
            )}
          </>
        )}

        {activeTab === "runs" && <RunsTab />}
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
