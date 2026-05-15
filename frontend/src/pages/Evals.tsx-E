import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BarChart3, Plus, RefreshCw } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import { DatasetCard } from "@/components/evals/DatasetCard"
import { DatasetDetail } from "@/components/evals/DatasetDetail"
import { GenerateDatasetDialog } from "@/components/evals/GenerateDatasetDialog"
import { RunEvalDialog } from "@/components/evals/RunEvalDialog"
import type {
  DatasetSize,
  DocumentOption,
  EvalRunSummary,
  GoldenDataset,
  GoldenDatasetDetail,
} from "@/components/evals/types"
import { Skeleton } from "@/components/ui/skeleton"
import { apiDelete, apiGet, apiPost } from "@/lib/apiClient"

const fetchDatasets = (): Promise<GoldenDataset[]> =>
  apiGet<GoldenDataset[]>("/evals/datasets")

const fetchDataset = (id: string): Promise<GoldenDatasetDetail> =>
  apiGet<GoldenDatasetDetail>(`/evals/datasets/${id}`, { limit: 50 })

const fetchDatasetRuns = (id: string): Promise<EvalRunSummary[]> =>
  apiGet<EvalRunSummary[]>(`/evals/datasets/${id}/runs`)

async function fetchDocuments(): Promise<DocumentOption[]> {
  const data = await apiGet<{ items: DocumentOption[] }>("/documents", {
    sort: "newest",
    page: 1,
    page_size: 100,
  })
  return data.items.filter((doc) => doc.stage === "complete")
}

export default function Evals() {
  const qc = useQueryClient()
  const [generateOpen, setGenerateOpen] = useState(false)
  const [runOpen, setRunOpen] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const datasetsQuery = useQuery({
    queryKey: ["eval-datasets"],
    queryFn: fetchDatasets,
    refetchInterval: (query) => {
      const data = query.state.data as GoldenDataset[] | undefined
      return data?.some((dataset) => dataset.status === "generating" || dataset.status === "pending")
        ? 5000
        : false
    },
  })

  const documentsQuery = useQuery({
    queryKey: ["eval-documents"],
    queryFn: fetchDocuments,
  })

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

  const createMutation = useMutation({
    mutationFn: (payload: {
      name: string
      size: DatasetSize
      document_ids: string[]
      generator_model?: string
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
    }) => apiPost(`/evals/datasets/${selectedId}/run`, payload),
    onSuccess: () => {
      setRunOpen(false)
      void qc.invalidateQueries({ queryKey: ["eval-dataset-runs", selectedId] })
      toast.success("Eval run started")
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

  const dbDatasets = useMemo(
    () => (datasetsQuery.data || []).filter((dataset) => dataset.source === "db"),
    [datasetsQuery.data],
  )
  const fileDatasets = useMemo(
    () => (datasetsQuery.data || []).filter((dataset) => dataset.source === "file"),
    [datasetsQuery.data],
  )

  return (
    <div className="flex h-full flex-col overflow-hidden bg-background">
      <header className="flex shrink-0 items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">Evals</h1>
          <p className="text-sm text-muted-foreground">Generate datasets and track quality scores.</p>
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

      <main className="min-h-0 flex-1 overflow-auto p-6">
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
            <section className="grid gap-3">
              <h2 className="text-sm font-semibold">Generated Datasets</h2>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {dbDatasets.map((dataset) => (
                  <DatasetCard
                    key={dataset.id || dataset.name}
                    dataset={dataset}
                    selected={dataset.id === selectedId}
                    onSelect={() => setSelectedId(dataset.id)}
                  />
                ))}
              </div>
            </section>

            {fileDatasets.length > 0 && (
              <section className="grid gap-3">
                <h2 className="text-sm font-semibold">File Goldens</h2>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {fileDatasets.map((dataset) => (
                    <DatasetCard
                      key={dataset.name}
                      dataset={dataset}
                      selected={false}
                      onSelect={() => undefined}
                    />
                  ))}
                </div>
              </section>
            )}
          </div>
        )}
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
        open={Boolean(selectedId)}
        detail={detailQuery.data}
        runs={runsQuery.data || []}
        loading={detailQuery.isLoading}
        onOpenChange={(open) => {
          if (!open) setSelectedId(null)
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
