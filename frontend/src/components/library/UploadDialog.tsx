import { useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, Upload, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { logger } from "@/lib/logger"
import { Progress } from "@/components/ui/progress"

const API_BASE = "http://localhost:8000"

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

const CONTENT_TYPE_OPTIONS = [
  {
    value: "book" as const,
    label: "Book",
    description: "For novels, non-fiction, full-length documents",
  },
  {
    value: "conversation" as const,
    label: "Conversation",
    description: "For chat exports, interviews, meeting transcripts",
  },
  {
    value: "notes" as const,
    label: "Notes",
    description: "For personal notes, articles, papers, web clips",
  },
  {
    value: "audio" as const,
    label: "Audio",
    description: "For lectures, podcasts, recorded talks (MP3, M4A, WAV)",
  },
  {
    value: "video" as const,
    label: "Video",
    description: "For lecture recordings, screen captures, video talks (MP4)",
  },
  {
    value: "epub" as const,
    label: "EPUB",
    description: "For EPUB e-books (auto-detected from .epub files)",
  },
]

type ContentTypeValue = "book" | "conversation" | "notes" | "audio" | "video" | "epub"
type DialogTab = "upload" | "paste" | "youtube"
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

async function submitFile(file: File, contentType: ContentTypeValue): Promise<string> {
  const form = new FormData()
  form.append("file", file)
  form.append("content_type", contentType)
  const res = await fetch(`${API_BASE}/documents/ingest`, { method: "POST", body: form })
  if (!res.ok) throw new Error("Upload failed")
  const data = (await res.json()) as { document_id: string }
  return data.document_id
}

async function submitKindleFile(file: File): Promise<{ document_ids: string[]; book_count: number }> {
  const form = new FormData()
  form.append("file", file)
  const res = await fetch(`${API_BASE}/documents/ingest-kindle`, { method: "POST", body: form })
  if (!res.ok) {
    const data = (await res.json()) as { detail?: string }
    throw new Error(data.detail ?? "Kindle import failed")
  }
  return res.json() as Promise<{ document_ids: string[]; book_count: number }>
}

function isKindleClippings(filename: string): boolean {
  return /clippings/i.test(filename)
}

async function submitYouTubeUrl(url: string): Promise<string> {
  const res = await fetch(`${API_BASE}/documents/ingest-url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) {
    const data = (await res.json()) as { detail?: string }
    throw new Error(data.detail ?? "YouTube ingestion failed")
  }
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
  const [uploadType, setUploadType] = useState<ContentTypeValue | null>(null)
  const [pasteLabel, setPasteLabel] = useState("")
  const [pasteText, setPasteText] = useState("")
  const [pasteType, setPasteType] = useState<ContentTypeValue | null>(null)
  const [typeError, setTypeError] = useState(false)
  const [youtubeUrl, setYoutubeUrl] = useState("")
  const [youtubeUrlError, setYoutubeUrlError] = useState("")
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Upload progress state
  const [mode, setMode] = useState<Mode>("idle")
  const [progress, setProgress] = useState(0)
  const [stageLabel, setStageLabel] = useState("")
  const [currentStage, setCurrentStage] = useState("")
  const [errorMessage, setErrorMessage] = useState("")
  const [docTitle, setDocTitle] = useState("")
  const [fileSizeMB, setFileSizeMB] = useState(0)

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const autoCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const uploadStartRef = useRef<number>(0)

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
    setUploadType(null)
    setPasteLabel("")
    setPasteText("")
    setPasteType(null)
    setTypeError(false)
    setYoutubeUrl("")
    setYoutubeUrlError("")
    setTab("upload")
    setMode("idle")
    setProgress(0)
    setStageLabel("")
    setCurrentStage("")
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
    if (file && isAccepted(file)) {
      setSelectedFile(file)
      // Auto-set type for EPUB files
      if (file.name.toLowerCase().endsWith(".epub")) setUploadType("epub")
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file && isAccepted(file)) {
      setSelectedFile(file)
      // Auto-set type for EPUB files
      if (file.name.toLowerCase().endsWith(".epub")) setUploadType("epub")
    }
  }

  // Time estimate — stage-aware.
  // Embedding and entity extraction are CPU-bound and can run for many minutes
  // on large documents. A fixed countdown is misleading for those stages.
  // Fast early stages (parse, classify, chunk) get a rough countdown.
  const SLOW_STAGES = new Set(["embedding", "entity_extract"])

  function timeEstimate(): string {
    if (progress >= 95 || mode !== "processing") return ""
    if (SLOW_STAGES.has(currentStage)) {
      // Don't show a lying countdown — acknowledge the wait qualitatively.
      return fileSizeMB > 0.3
        ? "Large documents can take several minutes here"
        : "Processing..."
    }
    // For fast early stages give a rough elapsed-based countdown.
    const totalSec = Math.max(20, 15 + Math.ceil(fileSizeMB * 60))
    const elapsed = Math.ceil((Date.now() - uploadStartRef.current) / 1000)
    const remaining = Math.max(0, totalSec - elapsed)
    if (remaining <= 0) return "Almost done..."
    if (remaining > 120) return `About ${Math.ceil(remaining / 60)} min remaining`
    return `About ${remaining}s remaining`
  }

  function startPolling(docId: string, filename: string, startTime: number) {
    pollIntervalRef.current = setInterval(() => {
      void (async () => {
        try {
          const res = await fetch(`${API_BASE}/documents/${docId}/status`)
          if (!res.ok) return
          const data = (await res.json()) as StatusResponse

          if (data.stage === "error" || data.error_message) {
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
          setCurrentStage(data.stage)
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

  async function doSubmit(file: File, title: string, contentType: ContentTypeValue) {
    const startTime = Date.now()
    uploadStartRef.current = startTime
    const sizeMB = file.size / (1024 * 1024)
    setFileSizeMB(sizeMB)
    setMode("uploading")
    setProgress(0)
    setStageLabel("Uploading...")
    setDocTitle(title)
    logger.info("[Upload] start", { filename: file.name, size_mb: sizeMB.toFixed(2), content_type: contentType })

    try {
      const docId = await submitFile(file, contentType)
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

    // Kindle My Clippings.txt: bypass normal content type selection
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
    const startTime = Date.now()
    uploadStartRef.current = startTime
    setMode("uploading")
    setProgress(0)
    setStageLabel("Uploading Kindle clippings...")
    setDocTitle(file.name)
    logger.info("[Upload] kindle start", { filename: file.name })
    try {
      const result = await submitKindleFile(file)
      const bookCount = result.book_count
      logger.info("[Upload] kindle uploaded", { filename: file.name, book_count: bookCount })
      setProgress(100)
      setStageLabel(`Imported ${bookCount} book${bookCount !== 1 ? "s" : ""}!`)
      setMode("success")
      toast.success(`Imported ${bookCount} book${bookCount !== 1 ? "s" : ""} from Kindle clippings`)
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
      void queryClient.invalidateQueries({ queryKey: ["documents-recent"] })
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
    const filename =
      pasteLabel.trim().replace(/[^a-z0-9_-]/gi, "_").toLowerCase() + ".txt"
    const file = new File([pasteText], filename, { type: "text/plain" })
    await doSubmit(file, pasteLabel.trim(), pasteType)
  }

  async function handleYouTubeSubmit() {
    const url = youtubeUrl.trim()
    if (!url) {
      setYoutubeUrlError("Enter a YouTube URL")
      return
    }
    if (!url.includes("youtube.com/watch") && !url.includes("youtu.be/")) {
      setYoutubeUrlError("Must be a YouTube watch URL (youtube.com/watch?v= or youtu.be/)")
      return
    }
    setYoutubeUrlError("")
    const startTime = Date.now()
    uploadStartRef.current = startTime
    setMode("uploading")
    setProgress(0)
    setStageLabel("Downloading audio from YouTube...")
    setDocTitle(url)
    logger.info("[Upload] youtube start", { url })
    try {
      const docId = await submitYouTubeUrl(url)
      toast.loading("Processing YouTube video...", { id: docId })
      setMode("processing")
      setProgress(5)
      setStageLabel("Transcribing...")
      startPolling(docId, url, startTime)
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "YouTube ingestion failed."
      logger.error("[Upload] youtube failed", { error_message: errMsg, url })
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
    } else if (tab === "youtube" && youtubeUrl.trim()) {
      await handleYouTubeSubmit()
    } else {
      setMode("idle")
    }
  }

  if (!open) return null

  const isActive = mode === "uploading" || mode === "processing"

  // Shared RadioGroup for content type selection
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
              {(["upload", "paste", "youtube"] as const).map((t) => (
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
                  {t === "upload" ? "Upload File" : t === "paste" ? "Paste Text" : "YouTube URL"}
                </button>
              ))}
            </div>

            {tab === "youtube" ? (
              <div className="space-y-4">
                <div>
                  <label className="mb-1 block text-sm font-medium text-foreground">
                    YouTube URL <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="url"
                    value={youtubeUrl}
                    onChange={(e) => {
                      setYoutubeUrl(e.target.value)
                      setYoutubeUrlError("")
                    }}
                    placeholder="https://www.youtube.com/watch?v=..."
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                  {youtubeUrlError && (
                    <p className="mt-1 text-xs text-red-600">{youtubeUrlError}</p>
                  )}
                  {!youtubeUrl && !youtubeUrlError && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      Audio is downloaded and transcribed locally. No file is uploaded to any service.
                    </p>
                  )}
                </div>
                <button
                  onClick={() => void handleYouTubeSubmit()}
                  disabled={!youtubeUrl.trim()}
                  className="w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                >
                  Ingest
                </button>
              </div>
            ) : tab === "upload" ? (
              <div className="space-y-4">
                {/* Content type selector — hidden for auto-detected formats */}
                {selectedFile && isKindleClippings(selectedFile.name) ? (
                  <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
                    <p className="text-sm font-medium text-amber-800">Kindle clippings detected</p>
                    <p className="text-xs text-amber-700">
                      Each book's highlights will be imported as a separate document tagged with Kindle.
                    </p>
                  </div>
                ) : (
                  <ContentTypeRadioGroup
                    value={uploadType}
                    onChange={setUploadType}
                  />
                )}

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
                  disabled={!selectedFile || (!uploadType && !(selectedFile && isKindleClippings(selectedFile.name)))}
                  className="w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                >
                  Ingest
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Content type selector */}
                <ContentTypeRadioGroup
                  value={pasteType}
                  onChange={setPasteType}
                />

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
