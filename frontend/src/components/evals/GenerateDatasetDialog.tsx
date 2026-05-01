import { useState } from "react"
import { AlertTriangle, Plus } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import type { DatasetSize, DocumentOption } from "./types"

const SIZE_OPTIONS: Array<{ value: DatasetSize; label: string; hint: string }> = [
  { value: "small", label: "Small", hint: "~10/doc" },
  { value: "medium", label: "Medium", hint: "~50/doc" },
  { value: "large", label: "Large", hint: "~200/doc" },
]

const MODEL_OPTIONS = ["ollama/gemma4", "ollama/mistral", "openai/gpt-4o-mini", "anthropic/claude-3-5-haiku"]

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
  const [size, setSize] = useState<DatasetSize>("small")
  const [documentIds, setDocumentIds] = useState<string[]>([])
  const [model, setModel] = useState(MODEL_OPTIONS[0])
  const external = /^(openai|anthropic|gemini)\//.test(model)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Generate Dataset</DialogTitle>
          <DialogDescription>Create grounded golden questions from ingested documents.</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <label className="grid gap-1 text-sm">
            <span className="font-medium">Name</span>
            <input
              className="h-9 rounded-md border bg-background px-3 text-sm"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Chapter 4 retrieval baseline"
            />
          </label>

          <div className="grid gap-2">
            <div className="text-sm font-medium">Size</div>
            <div className="grid grid-cols-3 gap-2">
              {SIZE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={`rounded-md border p-3 text-left text-sm ${
                    size === option.value ? "border-primary bg-primary/5" : "hover:bg-accent"
                  }`}
                  onClick={() => setSize(option.value)}
                >
                  <div className="font-medium">{option.label}</div>
                  <div className="text-xs text-muted-foreground">{option.hint}</div>
                </button>
              ))}
            </div>
          </div>

          <label className="grid gap-1 text-sm">
            <span className="font-medium">Generator Model</span>
            <select
              className="h-9 rounded-md border bg-background px-3 text-sm"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            >
              {MODEL_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
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

          <div className="grid gap-2">
            <div className="text-sm font-medium">Documents</div>
            <div className="max-h-56 overflow-auto rounded-md border">
              {loadingDocuments ? (
                <div className="p-3 text-sm text-muted-foreground">Loading documents...</div>
              ) : (
                documents.map((doc) => (
                  <label key={doc.id} className="flex items-center gap-2 border-b px-3 py-2 text-sm last:border-b-0">
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
          </div>
        </div>

        <DialogFooter>
          <button
            type="button"
            className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-50"
            disabled={submitting || !name.trim() || documentIds.length === 0}
            onClick={() => onSubmit({ name: name.trim(), size, document_ids: documentIds, generator_model: model })}
          >
            <Plus className="h-4 w-4" />
            Generate
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
