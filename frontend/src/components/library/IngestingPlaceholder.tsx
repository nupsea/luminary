import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useMutation } from "@tanstack/react-query"
import { AlertTriangle, ArrowLeft, Loader2, Trash2 } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { apiDelete } from "@/lib/apiClient"
import { fetchIngestionStatus, type IngestionStatus } from "@/lib/ingestionApi"
import { Progress } from "@/components/ui/progress"

const STAGE_LABELS: Record<string, string> = {
  parsing: "Parsing document",
  transcribing: "Transcribing",
  classifying: "Classifying content",
  chunking: "Chunking text",
  embedding: "Generating embeddings",
  indexing: "Building keyword index",
  entity_extract: "Extracting entities",
  complete: "Complete",
  error: "Failed",
}

interface IngestingPlaceholderProps {
  documentId: string
  title: string
  /** Initial stage from the cached document list, used until the first poll lands. */
  initialStage?: string
  onBack: () => void
}

const deleteDocument = (documentId: string): Promise<void> =>
  apiDelete(`/documents/${documentId}`)

/**
 * Stand-in for DocumentReader while a document is mid-ingestion or has errored.
 *
 * Polls the per-doc status endpoint every 2s. When the doc reaches `complete`
 * it invalidates queries so the parent's cached list refreshes; the parent
 * (Learning.tsx) re-evaluates the readiness gate and swaps in DocumentReader.
 *
 * "Cancel & delete" hits DELETE /documents/{id}, which now cancels the
 * in-flight ingestion task on the backend before tearing down rows.
 */
export function IngestingPlaceholder({
  documentId,
  title,
  initialStage = "parsing",
  onBack,
}: IngestingPlaceholderProps) {
  const queryClient = useQueryClient()
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  const { data: status } = useQuery<IngestionStatus>({
    queryKey: ["documents", documentId, "status"],
    queryFn: () => fetchIngestionStatus(documentId),
    refetchInterval: (query) => {
      const stage = query.state.data?.stage
      return stage === "complete" || stage === "error" ? false : 2000
    },
    initialData: { stage: initialStage, progress_pct: 0, done: false, error_message: null },
  })

  const stage = status?.stage ?? initialStage
  const progress = status?.progress_pct ?? 0
  const isErrored = stage === "error"
  const isComplete = stage === "complete"

  // When ingestion completes, invalidate the documents list so the parent
  // gate picks up the new readiness on its next render.
  useEffect(() => {
    if (isComplete) {
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
      void queryClient.invalidateQueries({ queryKey: ["documents-recent"] })
      void queryClient.invalidateQueries({ queryKey: ["document", documentId] })
    }
  }, [isComplete, documentId, queryClient])

  const deleteMutation = useMutation({
    mutationFn: () => deleteDocument(documentId),
    onSuccess: () => {
      toast.success(`Deleted "${title}"`)
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
      void queryClient.invalidateQueries({ queryKey: ["documents-recent"] })
      onBack()
    },
    onError: () => {
      toast.error("Failed to delete document")
    },
  })

  const stageLabel = STAGE_LABELS[stage] ?? `Processing (${progress}%)`

  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 p-6">
      <div className="flex w-full max-w-lg flex-col gap-5 rounded-lg border border-border bg-background p-6 shadow-sm">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              {isErrored ? "Ingestion failed" : "Preparing document"}
            </p>
            <h2 className="mt-1 truncate text-base font-semibold text-foreground">{title}</h2>
          </div>
          {isErrored ? (
            <AlertTriangle className="shrink-0 text-red-500" size={22} />
          ) : (
            <Loader2 className="shrink-0 animate-spin text-primary" size={22} />
          )}
        </div>

        {isErrored ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {status?.error_message ?? "The ingestion pipeline did not finish. You can delete and retry."}
          </div>
        ) : (
          <>
            <Progress value={progress} />
            <div className="flex items-center justify-between text-sm">
              <span className="text-foreground">{stageLabel}</span>
              <span className="text-xs text-muted-foreground">{progress}%</span>
            </div>
            <p className="text-xs text-muted-foreground">
              Learning features (Study, Visualize, Chat, flashcards, search) become available once
              ingestion completes. You can keep using the rest of Luminary while this runs.
            </p>
          </>
        )}

        <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
          <button
            onClick={onBack}
            className="flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-accent"
          >
            <ArrowLeft size={14} />
            Back to library
          </button>
          {confirmingDelete ? (
            <>
              <span className="text-xs text-muted-foreground">
                {isErrored ? "Delete?" : "Cancel ingestion and delete?"}
              </span>
              <button
                onClick={() => deleteMutation.mutate()}
                disabled={deleteMutation.isPending}
                className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50"
              >
                {deleteMutation.isPending ? "Deleting…" : "Confirm delete"}
              </button>
              <button
                onClick={() => setConfirmingDelete(false)}
                className="rounded-md border border-border px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-accent"
              >
                Keep
              </button>
            </>
          ) : (
            <button
              onClick={() => setConfirmingDelete(true)}
              className="flex items-center gap-1 rounded-md border border-red-200 bg-red-50 px-3 py-1.5 text-sm font-medium text-red-700 transition-colors hover:bg-red-100"
            >
              <Trash2 size={14} />
              {isErrored ? "Delete" : "Cancel & delete"}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
