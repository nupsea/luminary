import { useState } from "react"
import { AlertTriangle } from "lucide-react"
import type { DocumentOption, GoldenDataset } from "./types"

interface RelinkDatasetDialogProps {
  open: boolean
  dataset: GoldenDataset | null
  documents: DocumentOption[]
  submitting: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (payload: { document_id: string }) => void
}

// Repair dialog for a generated dataset whose pinned source document was
// deleted (all its runs score 0% because scoped retrieval finds nothing).
export function RelinkDatasetDialog({
  open,
  dataset,
  documents,
  submitting,
  onOpenChange,
  onSubmit,
}: RelinkDatasetDialogProps) {
  const [documentId, setDocumentId] = useState("")
  if (!open || !dataset) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-lg border bg-card p-5 shadow-lg">
        <div className="mb-2 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-600" />
          <h3 className="text-sm font-semibold">Re-link {dataset.name}</h3>
        </div>
        <p className="mb-3 text-xs text-muted-foreground">
          The document this dataset was generated from was deleted from the library, so every
          eval run scores 0%. Pick the re-ingested document to point the questions at. Scores
          will only be meaningful if the new document has the same content.
        </p>
        <label className="grid gap-1 text-xs">
          <span className="font-medium text-muted-foreground">Live document</span>
          <select
            className="h-9 rounded-md border bg-background px-2 text-sm"
            value={documentId}
            onChange={(e) => setDocumentId(e.target.value)}
          >
            <option value="">Select a document…</option>
            {documents.map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.title}
              </option>
            ))}
          </select>
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            className="h-9 rounded-md border px-3 text-sm hover:bg-accent"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!documentId || submitting}
            className="h-9 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-50"
            onClick={() => onSubmit({ document_id: documentId })}
          >
            Re-link
          </button>
        </div>
      </div>
    </div>
  )
}
