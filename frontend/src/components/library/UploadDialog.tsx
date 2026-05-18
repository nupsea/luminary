import { useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, Upload, X } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { logger } from "@/lib/logger"
import { Progress } from "@/components/ui/progress"

import {
  type ContentTypeValue,
  submitFile,
  submitKindleFile,
  submitUrl,
} from "@/lib/ingestionApi"
import { useIngestionJob, useIngestionTracker } from "@/hooks/ingestionTrackerCore"

const ACCEPTED_TYPES = [".pdf", ".docx", ".txt", ".md", ".mp3", ".m4a", ".wav", ".mp4", ".epub"]

const STAGE_LABELS: Record<string, string> = {
  parsing: "Parsing document...",
  transcribing: "Transcribing...",
  classifying: "Classifying content...",
  chunking: "Chunking text...",
  embedding: "Generating embeddings...",
  indexing: "Building keyword index...",
  entity_extract: "Extracting entities...",
  complete: "Complete!",
}

const SLOW_STAGES = new Set(["embedding", "entity_extract"])

const CONTENT_TYPE_OPTIONS = [
  { value: "book" as const, label: "Book", description: "For novels, non-fiction, full-length documents" },
  { value: "tech_book" as const, label: "Tech Book", description: "For programming/CS books with code blocks and numbered sections (enables per-section Feynman)" },
  { value: "tech_article" as const, label: "Tech Article", description: "For technical articles, blog posts, and short technical writing" },
  { value: "conversation" as const, label: "Conversation", description: "For chat exports, interviews, meeting transcripts" },
  { value: "notes" as const, label: "Notes", description: "For personal notes, articles, papers, web clips" },
  { value: "audio" as const, label: "Audio", description: "For lectures, podcasts, recorded talks (MP3, M4A, WAV)" },
  { value: "video" as const, label: "Video", description: "For lecture recordings, screen captures, video talks (MP4)" },
  { value: "epub" as const, label: "EPUB", description: "For EPUB e-books (auto-detected from .epub files)" },
]

type DialogTab = "upload" | "paste" | "url"
// "uploading"  = synchronous HTTP POST in flight (blocks close, brief)
// "tracking"   = doc accepted by backend, ingestion running in the global tracker
// "success"    = the doc this dialog launched finished
// "error"      = upload-time failure (tracker errors are surfaced via toast)
type Mode = "idle" | "uploading" | "tracking" | "success" | "error"

interface UploadDialogProps {
  open: boolean
  onClose: () => void
}

function isKindleClippings(filename: string): boolean {
  return /clippings/i.test(filename)
}

export function UploadDialog({ open, onClose }: UploadDialogProps) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { track } = useIngestionTracker()

  const [tab, setTab] = useState<DialogTab>("upload")
  const [isDragging, setIsDragging] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploadType, setUploadType] = useState<ContentTypeValue | null>(null)
  const [pasteLabel, setPasteLabel] = useState("")
  const [pasteText, setPasteText] = useState("")
  const [pasteType, setPasteType] = useState<ContentTypeValue | null>(null)
  const [typeError, setTypeError] = useState(false)
  const [url, setUrl] = useState("")
  const [urlError, setUrlError] = useState("")
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [mode, setMode] = useState<Mode>("idle")
  const [errorMessage, setErrorMessage] = useState("")
  const [docTitle, setDocTitle] = useState("")
  const [fileSizeMB, setFileSizeMB] = useState(0)
  const [trackedDocId, setTrackedDocId] = useState<string | null>(null)
  const uploadStartRef = useRef<number>(0)
  const autoCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const trackedJob = useIngestionJob(trackedDocId)

  // Surface tracker errors / completions for the doc this dialog launched.
  useEffect(() => {
    if (!trackedJob) return
    if (trackedJob.status === "complete" && mode === "tracking") {
      setMode("success")
      autoCloseTimerRef.current = setTimeout(() => {
        reset()
        onClose()
      }, 3000)
    } else if (trackedJob.status === "error" && mode === "tracking") {
      setMode("error")
      setErrorMessage(trackedJob.errorMessage ?? "Ingestion failed")
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trackedJob?.status])

  function clearAutoClose() {
    if (autoCloseTimerRef.current) {
      clearTimeout(autoCloseTimerRef.current)
      autoCloseTimerRef.current = null
    }
  }

  useEffect(() => () => clearAutoClose(), [])

  function reset() {
    clearAutoClose()
    setSelectedFile(null)
    setUploadType(null)
    setPasteLabel("")
    setPasteText("")
    setPasteType(null)
    setTypeError(false)
    setUrl("")
    setUrlError("")
    setTab("upload")
    setMode("idle")
    setErrorMessage("")
    setDocTitle("")
    setFileSizeMB(0)
    setTrackedDocId(null)
  }

  function handleClose() {
    // Only block close during the brief synchronous upload POST. Once the doc is
    // accepted by the backend, ingestion runs in the global tracker and the user
    // is free to dismiss the dialog -- progress surfaces via toasts and the library list.
    if (mode === "uploading") return
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
    if (file && isAccepted(file)) {
      setSelectedFile(file)
      if (file.name.toLowerCase().endsWith(".epub")) setUploadType("epub")
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file && isAccepted(file)) {
      setSelectedFile(file)
      if (file.name.toLowerCase().endsWith(".epub")) setUploadType("epub")
    }
  }

  const progress = mode === "success" ? 100 : trackedJob?.progressPct ?? 0
  const currentStage = trackedJob?.stage ?? ""
  const stageLabel = useMemo(() => {
    if (mode === "uploading") return "Uploading..."
    if (mode === "success") return "Complete!"
    if (currentStage) return STAGE_LABELS[currentStage] ?? `Processing (${progress}%)...`
    return ""
  }, [mode, currentStage, progress])

  function timeEstimate(): string {
    if (mode !== "tracking" || progress >= 95) return ""
    if (SLOW_STAGES.has(currentStage)) {
      return fileSizeMB > 0.3 ? "Large documents can take several minutes here" : "Processing..."
    }
    const totalSec = Math.max(20, 15 + Math.ceil(fileSizeMB * 60))
    const elapsed = Math.ceil((Date.now() - uploadStartRef.current) / 1000)
    const remaining = Math.max(0, totalSec - elapsed)
    if (remaining <= 0) return "Almost done..."
    if (remaining > 120) return `About ${Math.ceil(remaining / 60)} min remaining`
    return `About ${remaining}s remaining`
  }

  async function doSubmit(file: File, title: string, contentType: ContentTypeValue) {
    uploadStartRef.current = Date.now()
    const sizeMB = file.size / (1024 * 1024)
    setFileSizeMB(sizeMB)
    setMode("uploading")
    setDocTitle(title)
    logger.info("[Upload] start", { filename: file.name, size_mb: sizeMB.toFixed(2), content_type: contentType })

    try {
      const docId = await submitFile(file, contentType)
      logger.info("[Upload] uploaded", { filename: file.name, doc_id: docId })
      track(docId, title)
      setTrackedDocId(docId)
      // Close the dialog immediately — progress is shown via the
      // IngestionProgressPills widget in the bottom-left corner.
      reset()
      onClose()
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
    if (isKindleClippings(selectedFile.name)) {
      await doSubmitKindle(selectedFile)
      return
    }
    if (!uploadType) {
      setTypeError(true)
      return
    }
    setTypeError(false)
    const title = selectedFile.name.replace(/\.[^/.]+$/, "")
    await doSubmit(selectedFile, title, uploadType)
  }

  async function doSubmitKindle(file: File) {
    uploadStartRef.current = Date.now()
    setMode("uploading")
    setDocTitle(file.name)
    logger.info("[Upload] kindle start", { filename: file.name })
    try {
      const result = await submitKindleFile(file)
      const bookCount = result.book_count
      logger.info("[Upload] kindle uploaded", { filename: file.name, book_count: bookCount })
      // Each Kindle book ingests independently in the background; register them all.
      for (const id of result.document_ids) track(id, `Kindle book (${id.slice(0, 8)})`)
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
      void queryClient.invalidateQueries({ queryKey: ["documents-recent"] })
      toast.success(`Imported ${bookCount} book${bookCount !== 1 ? "s" : ""} from Kindle clippings`)
      setMode("success")
      autoCloseTimerRef.current = setTimeout(() => {
        reset()
        onClose()
      }, 3000)
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "Kindle import failed."
      logger.error("[Upload] kindle failed", { error_message: errMsg, filename: file.name })
      setMode("error")
      setErrorMessage(errMsg)
      toast.error(errMsg)
    }
  }

  async function handlePasteSubmit() {
    if (!pasteLabel.trim() || !pasteText.trim()) return
    if (!pasteType) {
      setTypeError(true)
      return
    }
    setTypeError(false)
    const filename = pasteLabel.trim().replace(/[^a-z0-9_-]/gi, "_").toLowerCase() + ".txt"
    const file = new File([pasteText], filename, { type: "text/plain" })
    await doSubmit(file, pasteLabel.trim(), pasteType)
  }

  async function handleUrlSubmit() {
    const urlValue = url.trim()
    if (!urlValue) {
      setUrlError("Enter a URL")
      return
    }
    setUrlError("")
    uploadStartRef.current = Date.now()
    setMode("uploading")
    setDocTitle(urlValue)
    logger.info("[Upload] url start", { url: urlValue })
    try {
      const docId = await submitUrl(urlValue)
      track(docId, urlValue)
      setTrackedDocId(docId)
      // Close the dialog immediately — progress is shown via the
      // IngestionProgressPills widget in the bottom-left corner.
      reset()
      onClose()
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "Ingestion failed."
      logger.error("[Upload] url failed", { error_message: errMsg, url: urlValue })
      setMode("error")
      setErrorMessage(errMsg)
      toast.error(errMsg)
    }
  }

  async function handleRetry() {
    setErrorMessage("")
    if (tab === "upload" && selectedFile && uploadType) {
      await handleUploadSubmit()
    } else if (tab === "paste" && pasteLabel.trim() && pasteText.trim() && pasteType) {
      await handlePasteSubmit()
    } else if (tab === "url" && url.trim()) {
      await handleUrlSubmit()
    } else {
      setMode("idle")
    }
  }

  if (!open) return null

  // Only the synchronous upload POST blocks dialog dismissal. Tracking is
  // background work owned by the global tracker.
  const closeBlocked = mode === "uploading"
  const showProgress = mode === "uploading" || mode === "tracking"

  function ContentTypeRadioGroup({
    value,
    onChange,
  }: {
    value: ContentTypeValue | null
    onChange: (v: ContentTypeValue) => void
  }) {
    return (
      <div className="space-y-2">
        <label className="block text-sm font-medium text-foreground">
          Document type <span className="text-red-500">*</span>
        </label>
        <div className="space-y-1.5">
          {CONTENT_TYPE_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2.5 transition-colors",
                value === opt.value
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50",
              )}
            >
              <input
                type="radio"
                name="content_type"
                value={opt.value}
                checked={value === opt.value}
                onChange={() => {
                  onChange(opt.value)
                  setTypeError(false)
                }}
                className="mt-0.5 accent-primary"
              />
              <div>
                <p className="text-sm font-medium text-foreground">{opt.label}</p>
                <p className="text-xs text-muted-foreground">{opt.description}</p>
              </div>
            </label>
          ))}
        </div>
        {typeError && (
          <p className="text-xs text-red-600">Please select a document type</p>
        )}
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className={cn("absolute inset-0 bg-black/40", closeBlocked ? "cursor-not-allowed" : "")}
        onClick={handleClose}
      />

      <div className="relative z-10 w-full max-w-lg rounded-lg border border-border bg-background p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-foreground">Add Content</h2>
          <button
            onClick={handleClose}
            disabled={closeBlocked}
            className="text-muted-foreground hover:text-foreground disabled:opacity-30"
          >
            <X size={18} />
          </button>
        </div>

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

        {showProgress && (
          <div className="flex flex-col gap-4 py-2">
            <Progress value={progress} />
            <div className="flex items-center justify-between text-sm">
              <span className="text-foreground">{stageLabel}</span>
              <span className="text-xs text-muted-foreground">{timeEstimate()}</span>
            </div>
            <p className="text-center text-xs text-muted-foreground">
              {mode === "uploading"
                ? "Uploading file — please wait"
                : "Ingestion runs in the background. You can close this dialog and keep working."}
            </p>
          </div>
        )}

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

        {mode === "idle" && (
          <>
            <div className="mb-4 flex gap-1 rounded-md bg-muted p-1">
              {(["upload", "paste", "url"] as const).map((t) => (
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
                  {t === "upload" ? "Upload File" : t === "paste" ? "Paste Text" : "Web URL"}
                </button>
              ))}
            </div>

            {tab === "url" ? (
              <div className="space-y-4">
                <div>
                  <label className="mb-1 block text-sm font-medium text-foreground">
                    URL <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="url"
                    value={url}
                    onChange={(e) => {
                      setUrl(e.target.value)
                      setUrlError("")
                    }}
                    placeholder="https://example.com/article or YouTube URL"
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                  {urlError && (
                    <p className="mt-1 text-xs text-red-600">{urlError}</p>
                  )}
                  {!url && !urlError && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      Articles are extracted to Markdown. YouTube videos are transcribed. All processing is local.
                    </p>
                  )}
                </div>
                <button
                  onClick={() => void handleUrlSubmit()}
                  disabled={!url.trim()}
                  className="w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                >
                  Ingest
                </button>
              </div>
            ) : tab === "upload" ? (
              <div className="space-y-4">
                {selectedFile && isKindleClippings(selectedFile.name) ? (
                  <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
                    <p className="text-sm font-medium text-amber-800">Kindle clippings detected</p>
                    <p className="text-xs text-amber-700">
                      Each book's highlights will be imported as a separate document tagged with Kindle.
                    </p>
                  </div>
                ) : (
                  <ContentTypeRadioGroup value={uploadType} onChange={setUploadType} />
                )}

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
                  disabled={!selectedFile || (!uploadType && !(selectedFile && isKindleClippings(selectedFile.name)))}
                  className="w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                >
                  Ingest
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                <ContentTypeRadioGroup value={pasteType} onChange={setPasteType} />

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
                  disabled={!pasteLabel.trim() || !pasteText.trim() || !pasteType}
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
