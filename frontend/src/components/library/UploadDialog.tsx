import { useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, Upload, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { logger } from "@/lib/logger"
import { Progress } from "@/components/ui/progress"

const API_BASE = "http://localhost:8000"

const ACCEPTED_TYPES = [".pdf", ".docx", ".txt", ".md"]

const STAGE_LABELS: Record<string, string> = {
  parsing: "Parsing document...",
  classifying: "Classifying content...",
  chunking: "Chunking text...",
  embedding: "Generating embeddings...",
  indexing: "Building keyword index...",
  entity_extract: "Extracting entities...",
  complete: "Complete!",
}

type DialogTab = "upload" | "paste"
type ContentTypeOption = "auto" | "book" | "paper" | "conversation" | "notes"
type Mode = "idle" | "uploading" | "processing" | "success" | "error"

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
  const navigate = useNavigate()

  // Form state
  const [tab, setTab] = useState<DialogTab>("upload")
  const [isDragging, setIsDragging] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [pasteLabel, setPasteLabel] = useState("")
  const [pasteText, setPasteText] = useState("")
  const [pasteType, setPasteType] = useState<ContentTypeOption>("auto")
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Upload progress state
  const [mode, setMode] = useState<Mode>("idle")
  const [progress, setProgress] = useState(0)
  const [stageLabel, setStageLabel] = useState("")
  const [errorMessage, setErrorMessage] = useState("")
  const [docTitle, setDocTitle] = useState("")
  const [fileSizeMB, setFileSizeMB] = useState(0)

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const autoCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function clearPolling() {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
  }

  function clearAutoClose() {
    if (autoCloseTimerRef.current) {
      clearTimeout(autoCloseTimerRef.current)
      autoCloseTimerRef.current = null
    }
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      clearPolling()
      clearAutoClose()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function reset() {
    clearPolling()
    clearAutoClose()
    setSelectedFile(null)
    setPasteLabel("")
    setPasteText("")
    setPasteType("auto")
    setTab("upload")
    setMode("idle")
    setProgress(0)
    setStageLabel("")
    setErrorMessage("")
    setDocTitle("")
    setFileSizeMB(0)
  }

  function handleClose() {
    // Prevent close while upload/processing is active
    if (mode === "uploading" || mode === "processing") return
    reset()
    onClose()
  }

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

  // Time estimate: ~5s/MB for embedding + fixed overhead
  function timeEstimate(): string {
    if (progress >= 95 || mode !== "processing") return ""
    const totalSec = Math.max(10, Math.ceil(fileSizeMB * 5) + 10)
    const remaining = Math.ceil(totalSec * (1 - progress / 100))
    if (remaining <= 0) return ""
    return `About ${remaining}s remaining`
  }

  function startPolling(docId: string, filename: string, startTime: number) {
    pollIntervalRef.current = setInterval(() => {
      void (async () => {
        try {
          const res = await fetch(`${API_BASE}/documents/${docId}/status`)
          if (!res.ok) return
          const data = (await res.json()) as StatusResponse

          if (data.error_message ?? data.stage === "error") {
            clearPolling()
            const errMsg = data.error_message ?? "Ingestion failed"
            logger.error("[Upload] failed", { stage: data.stage, error_message: errMsg, doc_id: docId })
            setMode("error")
            setErrorMessage(errMsg)
            toast.error(errMsg, { id: docId })
            return
          }

          const label = STAGE_LABELS[data.stage] ?? `Processing (${data.progress_pct}%)...`
          logger.info("[Upload] stage", {
            stage: data.stage,
            progress_pct: data.progress_pct,
            doc_id: docId,
            filename,
          })
          setProgress(data.progress_pct)
          setStageLabel(label)
          setMode("processing")

          if (data.done) {
            clearPolling()
            const elapsed = Date.now() - startTime
            logger.info("[Upload] complete", { doc_id: docId, filename, elapsed_ms: elapsed })
            setProgress(100)
            setStageLabel("Complete!")
            setMode("success")
            toast.success("Document added successfully!", { id: docId })
            void queryClient.invalidateQueries({ queryKey: ["documents"] })
            void queryClient.invalidateQueries({ queryKey: ["documents-recent"] })
            // Auto-close after 3 seconds
            autoCloseTimerRef.current = setTimeout(() => {
              reset()
              onClose()
            }, 3000)
          }
        } catch {
          clearPolling()
          const errMsg = "Could not reach the server."
          logger.error("[Upload] failed", { stage: "poll", error_message: errMsg, doc_id: docId })
          setMode("error")
          setErrorMessage(errMsg)
          toast.error(errMsg, { id: docId })
        }
      })()
    }, 2000)
  }

  async function doSubmit(file: File, title: string) {
    const startTime = Date.now()
    const sizeMB = file.size / (1024 * 1024)
    setFileSizeMB(sizeMB)
    setMode("uploading")
    setProgress(0)
    setStageLabel("Uploading...")
    setDocTitle(title)
    logger.info("[Upload] start", { filename: file.name, size_mb: sizeMB.toFixed(2) })

    try {
      const docId = await submitFile(file)
      logger.info("[Upload] uploaded", { filename: file.name, doc_id: docId })
      toast.loading("Processing document...", { id: docId })
      setMode("processing")
      setProgress(5)
      setStageLabel("Parsing document...")
      startPolling(docId, file.name, startTime)
    } catch {
      const errMsg = "Upload failed. Please try again."
      logger.error("[Upload] failed", { stage: "upload", error_message: errMsg, filename: file.name })
      setMode("error")
      setErrorMessage(errMsg)
      toast.error(errMsg)
    }
  }

  async function handleUploadSubmit() {
    if (!selectedFile) return
    const title = selectedFile.name.replace(/\.[^/.]+$/, "")
    await doSubmit(selectedFile, title)
  }

  async function handlePasteSubmit() {
    if (!pasteLabel.trim() || !pasteText.trim()) return
    const filename =
      pasteLabel.trim().replace(/[^a-z0-9_-]/gi, "_").toLowerCase() + ".txt"
    const file = new File([pasteText], filename, { type: "text/plain" })
    await doSubmit(file, pasteLabel.trim())
  }

  async function handleRetry() {
    setErrorMessage("")
    if (tab === "upload" && selectedFile) {
      await handleUploadSubmit()
    } else if (tab === "paste" && pasteLabel.trim() && pasteText.trim()) {
      await handlePasteSubmit()
    } else {
      setMode("idle")
    }
  }

  if (!open) return null

  const isActive = mode === "uploading" || mode === "processing"

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop — click disabled while processing */}
      <div
        className={cn("absolute inset-0 bg-black/40", isActive ? "cursor-not-allowed" : "")}
        onClick={handleClose}
      />

      {/* Dialog */}
      <div className="relative z-10 w-full max-w-lg rounded-lg border border-border bg-background p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-foreground">Add Content</h2>
          <button
            onClick={handleClose}
            disabled={isActive}
            className="text-muted-foreground hover:text-foreground disabled:opacity-30"
          >
            <X size={18} />
          </button>
        </div>

        {/* ── Success state ── */}
        {mode === "success" && (
          <div className="flex flex-col items-center gap-4 py-6 text-center">
            <CheckCircle2 size={48} className="text-green-500" />
            <div>
              <p className="font-semibold text-foreground">{docTitle}</p>
              <p className="text-sm text-muted-foreground">Added successfully</p>
            </div>
            <button
              onClick={() => {
                reset()
                onClose()
                navigate("/")
              }}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
              View in library
            </button>
            <p className="text-xs text-muted-foreground">Closing in 3 seconds...</p>
          </div>
        )}

        {/* ── Progress state ── */}
        {(mode === "uploading" || mode === "processing") && (
          <div className="flex flex-col gap-4 py-2">
            <Progress value={progress} />
            <div className="flex items-center justify-between text-sm">
              <span className="text-foreground">{stageLabel}</span>
              <span className="text-xs text-muted-foreground">{timeEstimate()}</span>
            </div>
            <p className="text-center text-xs text-muted-foreground">
              Please wait — do not close this window
            </p>
          </div>
        )}

        {/* ── Error state ── */}
        {mode === "error" && (
          <div className="flex flex-col gap-4">
            <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3">
              <p className="text-sm font-medium text-red-700">Upload failed</p>
              <p className="mt-0.5 text-xs text-red-600">{errorMessage}</p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => void handleRetry()}
                className="flex-1 rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                Try again
              </button>
              <button
                onClick={() => {
                  setMode("idle")
                  setErrorMessage("")
                }}
                className="flex-1 rounded-md border border-border py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* ── Idle state — tabs and form ── */}
        {mode === "idle" && (
          <>
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
                  disabled={!selectedFile}
                  className="w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                >
                  Ingest
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
                  disabled={!pasteLabel.trim() || !pasteText.trim()}
                  className="w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                >
                  Ingest
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
