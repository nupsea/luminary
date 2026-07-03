import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { AlertTriangle, Plus } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { apiGet } from "@/lib/apiClient"
import type { DatasetSize, DocumentOption } from "./types"

// Preset buttons map to a question_count, not a size tier.
const PRESETS = [
  { label: "10", count: 10 },
  { label: "30", count: 30 },
  { label: "50", count: 50 },
  { label: "100", count: 100 },
]

// Static fallback when GET /evals/models is unavailable. The live list is
// preferred — it reflects the configured API keys and pulled Ollama models.
const FALLBACK_MODEL_OPTIONS = [
  "openai/gpt-5.4",
  "openai/gpt-5.1",
  "openai/gpt-4.1",
  "openai/gpt-4o-mini",
  "ollama/llama3.2",
  "ollama/mistral",
]

const fetchModels = () => apiGet<{ local: string[]; frontier: string[] }>("/evals/models")

interface GenerateDatasetDialogProps {
  open: boolean
  documents: DocumentOption[]
  loadingDocuments: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (payload: {
    name: string
    size: DatasetSize
    document_ids: string[]
    generator_model?: string
    question_count?: number
  }) => void
  submitting: boolean
}

export function GenerateDatasetDialog({
  open,
  documents,
  loadingDocuments,
  onOpenChange,
  onSubmit,
  submitting,
}: GenerateDatasetDialogProps) {
  const [name, setName] = useState("")
  const [questionCount, setQuestionCount] = useState<number>(30)
  const [documentIds, setDocumentIds] = useState<string[]>([])
  const modelsQuery = useQuery({
    queryKey: ["eval-models"],
    queryFn: fetchModels,
    enabled: open,
    staleTime: 60_000,
  })
  const fetched = modelsQuery.data
  const modelOptions =
    fetched && fetched.frontier.length + fetched.local.length > 0
      ? [...fetched.frontier, ...fetched.local]
      : FALLBACK_MODEL_OPTIONS
  const [model, setModel] = useState("")
  const effectiveModel = model || modelOptions[0]
  const external = /^(openai|anthropic|gemini)\//.test(effectiveModel)

  function handleSubmit() {
    onSubmit({
      name: name.trim(),
      size: "small",
      document_ids: documentIds,
      generator_model: effectiveModel,
      question_count: questionCount,
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Generate Dataset</DialogTitle>
          <DialogDescription>
            Create grounded golden Q&amp;A pairs from ingested documents for eval baselines.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <label className="grid gap-1 text-sm">
            <span className="font-medium">Name</span>
            <input
              className="h-9 rounded-md border bg-background px-3 text-sm"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="time-machine-baseline"
            />
          </label>

          <div className="grid gap-2">
            <div className="text-sm font-medium">
              Questions{" "}
              <span className="font-normal text-muted-foreground">
                — total across all selected documents
              </span>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex gap-1">
                {PRESETS.map((p) => (
                  <button
                    key={p.count}
                    type="button"
                    className={`rounded border px-3 py-1 text-xs font-medium transition-colors ${
                      questionCount === p.count
                        ? "border-primary bg-primary/10 text-primary"
                        : "hover:bg-accent"
                    }`}
                    onClick={() => setQuestionCount(p.count)}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <input
                type="number"
                min={1}
                max={500}
                className="h-8 w-20 rounded-md border bg-background px-2 text-sm"
                value={questionCount}
                onChange={(event) => {
                  const v = parseInt(event.target.value, 10)
                  if (!isNaN(v) && v >= 1 && v <= 500) setQuestionCount(v)
                }}
              />
            </div>
          </div>

          <label className="grid gap-1 text-sm">
            <span className="font-medium">Generator Model</span>
            <select
              className="h-9 rounded-md border bg-background px-3 text-sm"
              value={effectiveModel}
              onChange={(event) => setModel(event.target.value)}
            >
              {modelOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          {external && (
            <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
              <AlertTriangle className="h-4 w-4" />
              This will send document chunks to an external API.
            </div>
          )}

          <div className="grid gap-2">
            <div className="text-sm font-medium">Documents</div>
            <div className="max-h-56 overflow-auto rounded-md border">
              {loadingDocuments ? (
                <div className="p-3 text-sm text-muted-foreground">Loading documents...</div>
              ) : documents.length === 0 ? (
                <div className="p-3 text-sm text-muted-foreground">
                  No ingested documents yet. Ingest a document first.
                </div>
              ) : (
                documents.map((doc) => (
                  <label
                    key={doc.id}
                    className="flex cursor-pointer items-center gap-2 border-b px-3 py-2 text-sm last:border-b-0 hover:bg-accent/40"
                  >
                    <input
                      type="checkbox"
                      checked={documentIds.includes(doc.id)}
                      onChange={(event) => {
                        setDocumentIds((current) =>
                          event.target.checked
                            ? [...current, doc.id]
                            : current.filter((id) => id !== doc.id),
                        )
                      }}
                    />
                    <span className="min-w-0 flex-1 truncate">{doc.title}</span>
                    <span className="text-xs text-muted-foreground">{doc.content_type}</span>
                  </label>
                ))
              )}
            </div>
            {documentIds.length > 0 && (
              <div className="text-xs text-muted-foreground">
                {documentIds.length} doc{documentIds.length !== 1 ? "s" : ""} selected — up to {questionCount} questions total will be generated
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <button
            type="button"
            className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-50"
            disabled={submitting || !name.trim() || documentIds.length === 0}
            onClick={handleSubmit}
          >
            <Plus className="h-4 w-4" />
            Generate {questionCount} questions
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
