import { useState } from "react"
import { AlertTriangle } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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
  if (!dataset) return null
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            <span className="inline-flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-600" />
              Re-link {dataset.name}
            </span>
          </DialogTitle>
          <DialogDescription>
            The document this dataset was generated from was deleted from the library, so every
            eval run scores 0%. Pick the re-ingested document to point the questions at. Scores
            will only be meaningful if the new document has the same content.
          </DialogDescription>
        </DialogHeader>

        {documents.length === 0 ? (
          <div className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
            No completed documents in the library — ingest the document again, then re-link.
          </div>
        ) : (
          <label className="grid gap-1 text-sm">
            <span className="font-medium">Live document</span>
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
        )}

        <DialogFooter>
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
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
