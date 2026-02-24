import { useQueryClient } from "@tanstack/react-query"
import { Upload, X } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"

const API_BASE = "http://localhost:8000"

const ACCEPTED_TYPES = [".pdf", ".docx", ".txt", ".md"]
const STAGE_MESSAGES: Record<string, string> = {
  parsing: "Parsing document...",
  classifying: "Classifying content...",
  chunking: "Chunking text...",
  embedding: "Generating embeddings...",
  indexing: "Building keyword index...",
  complete: "Complete!",
}

type DialogTab = "upload" | "paste"
type ContentTypeOption = "auto" | "book" | "paper" | "conversation" | "notes"

interface StatusResponse {
  stage: string
  progress_pct: number
  done: boolean
  error_message: string | null
}

interface UploadDialogProps {
  open: boolean
  onClose: () => void
}

function pollStatus(documentId: string, toastId: string | number, onDone: () => void) {
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`${API_BASE}/documents/${documentId}/status`)
      if (!res.ok) return
      const data = (await res.json()) as StatusResponse

      if (data.error_message) {
        clearInterval(interval)
        toast.error(data.error_message, { id: toastId })
        return
      }

      const msg = STAGE_MESSAGES[data.stage] ?? `Processing (${data.progress_pct}%)...`
      toast.loading(msg, { id: toastId })

      if (data.done) {
        clearInterval(interval)
        toast.success("Document added successfully!", { id: toastId })
        onDone()
      }
    } catch {
      clearInterval(interval)
      toast.error("Could not reach the server.", { id: toastId })
    }
  }, 2000)
}

async function submitFile(file: File): Promise<string> {
  const form = new FormData()
  form.append("file", file)
  const res = await fetch(`${API_BASE}/documents/ingest`, { method: "POST", body: form })
  if (!res.ok) throw new Error("Upload failed")
  const data = (await res.json()) as { document_id: string }
  return data.document_id
}

export function UploadDialog({ open, onClose }: UploadDialogProps) {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<DialogTab>("upload")
  const [isDragging, setIsDragging] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [pasteLabel, setPasteLabel] = useState("")
  const [pasteText, setPasteText] = useState("")
  const [pasteType, setPasteType] = useState<ContentTypeOption>("auto")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  function isAccepted(file: File): boolean {
    return ACCEPTED_TYPES.some((ext) => file.name.toLowerCase().endsWith(ext))
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files[0]
    if (file && isAccepted(file)) setSelectedFile(file)
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file && isAccepted(file)) setSelectedFile(file)
  }

  function reset() {
    setSelectedFile(null)
    setPasteLabel("")
    setPasteText("")
    setPasteType("auto")
    setIsSubmitting(false)
    setTab("upload")
  }

  function handleClose() {
    reset()
    onClose()
  }

  async function handleUploadSubmit() {
    if (!selectedFile) return
    setIsSubmitting(true)
    const toastId = toast.loading("Uploading...")
    try {
      const documentId = await submitFile(selectedFile)
      onClose()
      reset()
      pollStatus(documentId, toastId, () => {
        void queryClient.invalidateQueries({ queryKey: ["documents"] })
      })
    } catch {
      setIsSubmitting(false)
      toast.error("Upload failed. Please try again.", { id: toastId })
    }
  }

  async function handlePasteSubmit() {
    if (!pasteLabel.trim() || !pasteText.trim()) return
    setIsSubmitting(true)
    const toastId = toast.loading("Uploading...")
    const filename =
      pasteLabel.trim().replace(/[^a-z0-9_-]/gi, "_").toLowerCase() + ".txt"
    const file = new File([pasteText], filename, { type: "text/plain" })
    try {
      const documentId = await submitFile(file)
      onClose()
      reset()
      pollStatus(documentId, toastId, () => {
        void queryClient.invalidateQueries({ queryKey: ["documents"] })
      })
    } catch {
      setIsSubmitting(false)
      toast.error("Upload failed. Please try again.", { id: toastId })
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40" onClick={handleClose} />

      {/* Dialog */}
      <div className="relative z-10 w-full max-w-lg rounded-lg border border-border bg-background p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-foreground">Add Content</h2>
          <button onClick={handleClose} className="text-muted-foreground hover:text-foreground">
            <X size={18} />
          </button>
        </div>

        {/* Tabs */}
        <div className="mb-4 flex gap-1 rounded-md bg-muted p-1">
          {(["upload", "paste"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "flex-1 rounded py-1.5 text-sm font-medium transition-colors",
                tab === t
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t === "upload" ? "Upload File" : "Paste Text"}
            </button>
          ))}
        </div>

        {tab === "upload" ? (
          <div className="space-y-4">
            {/* Drop zone */}
            <div
              onDragOver={(e) => {
                e.preventDefault()
                setIsDragging(true)
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
              className={cn(
                "flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 text-center transition-colors",
                isDragging
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50",
              )}
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload size={32} className="mb-2 text-muted-foreground" />
              {selectedFile ? (
                <div className="text-sm">
                  <p className="font-medium text-foreground">{selectedFile.name}</p>
                  <p className="text-muted-foreground">
                    {(selectedFile.size / 1024).toFixed(1)} KB
                  </p>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">
                  <p>Drag & drop or click to select</p>
                  <p className="mt-1 text-xs">{ACCEPTED_TYPES.join(", ")}</p>
                </div>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_TYPES.join(",")}
                className="hidden"
                onChange={handleFileChange}
              />
            </div>

            <button
              onClick={() => void handleUploadSubmit()}
              disabled={!selectedFile || isSubmitting}
              className="w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            >
              {isSubmitting ? "Uploading..." : "Ingest"}
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-foreground">
                Label <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={pasteLabel}
                onChange={(e) => setPasteLabel(e.target.value)}
                placeholder="Document title"
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-foreground">
                Content type
              </label>
              <select
                value={pasteType}
                onChange={(e) => setPasteType(e.target.value as ContentTypeOption)}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="auto">Auto-detect</option>
                <option value="book">Book</option>
                <option value="paper">Paper</option>
                <option value="conversation">Conversation</option>
                <option value="notes">Notes</option>
              </select>
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-foreground">
                Text <span className="text-red-500">*</span>
              </label>
              <textarea
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
                placeholder="Paste your text here..."
                rows={8}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>

            <button
              onClick={() => void handlePasteSubmit()}
              disabled={!pasteLabel.trim() || !pasteText.trim() || isSubmitting}
              className="w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            >
              {isSubmitting ? "Uploading..." : "Ingest"}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
