import { useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, Upload, X } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { apiGet, apiPost } from "@/lib/apiClient"
import type { CollectionTreeItem } from "@/lib/collectionUtils"
import { logger } from "@/lib/logger"
import { Progress } from "@/components/ui/progress"

import {
  type ContentTypeValue,
  submitFile,
  detectFileType,
  submitKindleFile,
  submitUrl,
} from "@/lib/ingestionApi"
import { useIngestionJob, useIngestionTracker } from "@/hooks/ingestionTrackerCore"
import { capabilityOf, useCapabilities } from "@/hooks/useSetup"
import type { CapabilityKey } from "@/lib/setupApi"

import {
  type Rejection,
  acceptedExtensions,
  describeRejection,
  detectContentType,
  toPickerValue,

  isKindleClippings,
} from "@/lib/uploadFileTypes"
import { ComponentsRequiredError } from "@/lib/apiClient"
import { InstallComponentButton } from "@/components/setup/InstallComponentButton"
import { useAppStore } from "@/store"

const STAGE_LABELS: Record<string, string> = {
  parsing: "Parsing document...",
  transcribing: "Transcribing...",
  classifying: "Classifying content...",
  chunking: "Chunking text...",
  embedding: "Generating embeddings...",
  indexing: "Building keyword index...",
  summarizing: "Summarising sections...",
  entity_extract: "Extracting entities...",
  complete: "Complete!",
}

const SLOW_STAGES = new Set(["embedding", "entity_extract"])

const CONTENT_TYPE_OPTIONS = [
  // "Book" reads as any long document, which put technical books here: the old
  // description said "non-fiction", the one word Technical also claims. Name
  // the writing rather than the length, and say what it is not.
  { value: "book" as const, label: "Book (prose)", description: "For novels, essays, history, biography, plays -- prose read start to finish. Not code or maths (including EPUB)" },
  { value: "technical" as const, label: "Tech Book", description: "For programming/CS books, manuals and long-form technical writing with code, formulae or numbered sections (sizing auto-tuned to length and structure)" },
  { value: "paper" as const, label: "Research Paper", description: "For academic papers with an abstract, method and references" },
  { value: "conversation" as const, label: "Conversation", description: "For chat exports, interviews, meeting transcripts" },
  { value: "notes" as const, label: "Notes", description: "For personal notes, web clips, short mixed content" },
  { value: "audio" as const, label: "Audio", description: "For lectures, podcasts, recorded talks (MP3, M4A, WAV)" },
  { value: "video" as const, label: "Video", description: "For lecture recordings, screen captures, video talks (MP4)" },
]

// Content types whose ingestion depends on an optional component.
const CONTENT_TYPE_CAPABILITY: Partial<Record<string, CapabilityKey>> = {
  audio: "audio_ingest",
  video: "video_ingest",
}

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


type ContentTypeOption = { value: ContentTypeValue; label: string; description: string }

/** Three dots breathing in sequence, to say work is happening without a spinner.
 *
 *  Staggered `animate-pulse` rather than a JS interval: no timer to leak, and it
 *  stops with the element instead of outliving it.
 */
function WorkingDots() {
  return (
    <span aria-hidden className="inline-flex gap-0.5 pl-0.5 align-baseline">
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="inline-block h-1 w-1 rounded-full bg-current animate-pulse"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </span>
  )
}

/** The document type, collapsed to the one line it usually is.
 *
 *  Seven options with a sentence each ran ~470px, so on the paste tab the
 *  fields the user actually came to fill sat below the fold. The type is
 *  auto-detected and rarely corrected, so the detected answer is what shows
 *  and the list is one click away.
 */
function ContentTypePicker({
  value,
  onChange,
  options,
  detecting = false,
}: {
  value: ContentTypeValue | null
  onChange: (v: ContentTypeValue) => void
  options: ContentTypeOption[]
  detecting?: boolean
}) {
  const [open, setOpen] = useState(false)
  const selected = options.find((o) => o.value === value) ?? null

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium text-foreground">Document type</span>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="text-xs font-medium text-primary hover:underline"
        >
          {open ? "Done" : "Change"}
        </button>
      </div>

      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="w-full rounded-md border border-border px-3 py-2 text-left transition-colors hover:border-primary/50"
        >
          <p className="text-sm font-medium text-foreground">
            {/* A choice the user has made outranks a detection still running:
                showing "Reading the document..." over their own selection reads
                as if the app were about to overrule them. It never does --
                detection is discarded once they pick. */}
            {selected ? (
              selected.label
            ) : detecting ? (
              <span className="inline-flex items-center">
                Reading the document
                <WorkingDots />
              </span>
            ) : (
              "Detect automatically"
            )}
          </p>
          <p className="text-xs text-muted-foreground">
            {selected
              ? detecting
                ? "Your choice. Add when you are ready."
                : `Detected. ${selected.description}`
              : detecting
                ? "Working out what this is. Pick one yourself to skip the wait."
                : "Luminary reads the document and decides. Change it if it gets it wrong."}
          </p>
        </button>
      ) : (
        <div role="radiogroup" aria-label="Document type" className="grid gap-1.5 sm:grid-cols-2">
          {options.map((opt) => (
            <label
              key={opt.value}
              title={opt.description}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-2 transition-colors",
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
                  setOpen(false)
                }}
                className="accent-primary"
              />
              <span className="text-sm text-foreground">{opt.label}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

export function UploadDialog({ open, onClose }: UploadDialogProps) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { track } = useIngestionTracker()

  const [tab, setTab] = useState<DialogTab>("url")
  // What this install can actually ingest. Offering a format we cannot process
  // sends the user through an upload that only fails at the transcription step.
  const { data: caps } = useCapabilities()
  const canAudio = capabilityOf(caps, "audio_ingest").available
  const canVideo = capabilityOf(caps, "video_ingest").available
  const canUrl =
    capabilityOf(caps, "web_ingest").available || capabilityOf(caps, "youtube_ingest").available
  const acceptedTypes = acceptedExtensions({ canAudio, canVideo })
  const contentTypeOptions = CONTENT_TYPE_OPTIONS.filter((o) => {
    const cap = CONTENT_TYPE_CAPABILITY[o.value]
    return !cap || capabilityOf(caps, cap).available
  })
  // Web URL leads: an article or a video is the most common thing to add and
  // the only one with nothing to prepare first. A file is second, and pasted
  // text -- which needs a title typed by hand -- is last.
  const availableTabs: DialogTab[] = canUrl ? ["url", "upload", "paste"] : ["upload", "paste"]
  const [isDragging, setIsDragging] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [rejection, setRejection] = useState<Rejection | null>(null)
  const [uploadType, setUploadType] = useState<ContentTypeValue | null>(null)
  // True once the user has explicitly picked a type; auto-detection from the
  // filename must never override an explicit choice.
  const typeTouchedRef = useRef(false)
  // Detection runs against the file the user just chose, so a slow one must not
  // overwrite the answer for a file they have since replaced.
  const detectSeqRef = useRef(0)
  const [detecting, setDetecting] = useState(false)
  const [pasteLabel, setPasteLabel] = useState("")
  const [pasteText, setPasteText] = useState("")
  const [pasteType, setPasteType] = useState<ContentTypeValue>("notes")
  const [url, setUrl] = useState("")
  const [urlError, setUrlError] = useState("")
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [mode, setMode] = useState<Mode>("idle")
  const [errorMessage, setErrorMessage] = useState("")
  // Components the failure can be fixed by installing, so the error offers the
  // install instead of telling the user to go and run a package manager.
  const [errorComponents, setErrorComponents] = useState<string[]>([])
  const [docTitle, setDocTitle] = useState("")
  const [fileSizeMB, setFileSizeMB] = useState(0)
  const [trackedDocId, setTrackedDocId] = useState<string | null>(null)
  // Collections to assign the new doc to at ingest (docs/02-ingest-and-doc-overview.md).
  const [selectedCollectionIds, setSelectedCollectionIds] = useState<string[]>([])
  const assignedRef = useRef(false)
  const uploadStartRef = useRef<number>(0)
  const autoCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const trackedJob = useIngestionJob(trackedDocId)

  const { data: collectionTree } = useQuery({
    queryKey: ["collections-tree"],
    queryFn: () => apiGet<CollectionTreeItem[]>("/collections/tree"),
    enabled: open,
  })

  // Once the doc is accepted (trackedDocId set), assign it to the chosen collections
  // via the tested POST /documents/{id}/collections. Fires once per upload.
  useEffect(() => {
    if (!trackedDocId || selectedCollectionIds.length === 0 || assignedRef.current) return
    assignedRef.current = true
    apiPost(`/documents/${trackedDocId}/collections`, { collection_ids: selectedCollectionIds })
      .then(() => queryClient.invalidateQueries({ queryKey: ["documents"] }))
      .catch((err) => {
        assignedRef.current = false
        logger.warn("[upload] collection assignment failed", { err })
      })
  }, [trackedDocId, selectedCollectionIds, queryClient])

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
      setErrorMessage(trackedJob.errorMessage ?? "Couldn't add the document")
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

  // A file dropped on the window arrives here already vetted by WindowDropZone.
  // Cleared on pickup so reopening the dialog does not resurrect it.
  const pendingUpload = useAppStore((s) => s.pendingUpload)
  const clearPendingUpload = useAppStore((s) => s.clearPendingUpload)
  useEffect(() => {
    if (!open || !pendingUpload) return
    // A dropped file is a file, whatever tab leads.
    setTab("upload")
    setSelectedFile(pendingUpload)
    setRejection(null)
    if (!typeTouchedRef.current) {
      setUploadType(detectContentType(pendingUpload.name))
      void runDetection(pendingUpload)
    }
    clearPendingUpload()
  }, [open, pendingUpload, clearPendingUpload])

  useEffect(() => {
    if (!canUrl && tab === "url") setTab("upload")
  }, [canUrl, tab])

  function reset() {
    clearAutoClose()
    setSelectedFile(null)
    setRejection(null)
    setUploadType(null)
    typeTouchedRef.current = false
    detectSeqRef.current += 1
    setDetecting(false)
    setPasteLabel("")
    setPasteText("")
    setPasteType("notes")
    setUrl("")
    setUrlError("")
    setTab(canUrl ? "url" : "upload")
    setMode("idle")
    setErrorMessage("")
    setErrorComponents([])
    setDocTitle("")
    setFileSizeMB(0)
    setTrackedDocId(null)
    setSelectedCollectionIds([])
    assignedRef.current = false
  }

  function handleClose() {
    // Only block close during the brief synchronous upload POST. Once the doc is
    // accepted by the backend, ingestion runs in the global tracker and the user
    // is free to dismiss the dialog -- progress surfaces via toasts and the library list.
    if (mode === "uploading") return
    reset()
    onClose()
  }

  // Accept, or say why not. Silently discarding the file read as a dead app,
  // especially for audio, which is refused only because a component is missing.
  function acceptFile(file: File) {
    const rejection = describeRejection(file.name, { canAudio, canVideo })
    if (rejection) {
      setRejection(rejection)
      return
    }
    setRejection(null)
    setSelectedFile(file)
    if (!typeTouchedRef.current) {
      setUploadType(detectContentType(file.name))
      void runDetection(file)
    }
  }

  /** Ask the backend what this file is, so the user can correct it before adding. */
  async function runDetection(file: File) {
    const fromName = detectContentType(file.name)
    // The extension already settles media and EPUB; reading those costs time
    // and cannot change the answer.
    if (fromName) return
    const seq = ++detectSeqRef.current
    setDetecting(true)
    try {
      const detected = await detectFileType(file)
      if (seq !== detectSeqRef.current) return
      // The classifier answers in the stored vocabulary; the picker offers a
      // narrower set. Mapping is what stops a correct answer rendering as no
      // answer at all.
      const value = toPickerValue(detected)
      logger.info("[Upload] type detected", {
        filename: file.name,
        detected,
        shown: value,
      })
      if (value && !typeTouchedRef.current) setUploadType(value)
    } finally {
      if (seq === detectSeqRef.current) setDetecting(false)
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) acceptFile(file)
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) acceptFile(file)
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

  async function doSubmit(file: File, title: string, contentType: ContentTypeValue | null) {
    uploadStartRef.current = Date.now()
    const sizeMB = file.size / (1024 * 1024)
    setFileSizeMB(sizeMB)
    setMode("uploading")
    setDocTitle(title)
    logger.info("[Upload] start", { filename: file.name, size_mb: sizeMB.toFixed(2), content_type: contentType })

    try {
      const { documentId: docId, duplicate } = await submitFile(file, contentType)
      logger.info("[Upload] uploaded", { filename: file.name, doc_id: docId, duplicate })
      if (duplicate) {
        // Ingestion dedupes on file hash and this copy is already complete, so
        // there is no job to follow. Tracking it would show a progress card that
        // never moves, which is what made a re-upload look like it did nothing.
        toast.success(`${title} is already in your library`)
        reset()
        onClose()
        return
      }
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
    const contentType = uploadType ?? detectContentType(selectedFile.name)
    const title = selectedFile.name.replace(/\.[^/.]+$/, "")
    await doSubmit(selectedFile, title, contentType)
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
      const { documentId, warnings } = await submitUrl(urlValue)
      track(documentId, urlValue)
      setTrackedDocId(documentId)
      // The dialog closes immediately, so any extraction notices need a long
      // dwell to survive the transition and stay readable.
      for (const warning of warnings) {
        toast.warning(warning, { duration: 12000 })
      }
      // Close the dialog immediately — progress is shown via the
      // IngestionProgressPills widget in the bottom-left corner.
      reset()
      onClose()
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "Couldn't add the document."
      logger.error("[Upload] url failed", { error_message: errMsg, url: urlValue })
      setMode("error")
      setErrorMessage(errMsg)
      setErrorComponents(err instanceof ComponentsRequiredError ? err.components : [])
      toast.error(errMsg)
    }
  }

  async function handleRetry() {
    setErrorMessage("")
    if (tab === "upload" && selectedFile) {
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
                navigate("/library")
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
                : "Processing runs in the background. You can close this dialog and keep working."}
            </p>
          </div>
        )}

        {mode === "error" && (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2 rounded-md border border-red-200 bg-red-50 px-4 py-3 dark:border-red-900 dark:bg-red-950/40">
              <div>
                <p className="text-sm font-medium text-red-700">
                  {errorComponents.length > 0 ? "One more step" : "Upload failed"}
                </p>
                <p className="mt-0.5 text-xs text-red-600">{errorMessage}</p>
              </div>
              {errorComponents.map((id) => (
                <InstallComponentButton key={id} componentId={id} />
              ))}
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
              {availableTabs.map((t) => (
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
                  Add
                </button>
              </div>
            ) : tab === "upload" ? (
              <div className="space-y-4">
                {selectedFile && isKindleClippings(selectedFile.name) ? (
                  <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 dark:border-amber-900 dark:bg-amber-950/40">
                    <p className="text-sm font-medium text-amber-800">Kindle clippings detected</p>
                    <p className="text-xs text-amber-700">
                      Each book's highlights will be imported as a separate document tagged with Kindle.
                    </p>
                  </div>
                ) : (
                  <ContentTypePicker
                    value={uploadType}
                    detecting={detecting}
                    options={contentTypeOptions}
                    onChange={(v) => {
                      typeTouchedRef.current = true
                      setUploadType(v)
                      // The user has decided, so the request in flight is moot.
                      // Bumping the sequence discards its result and clears the
                      // indicator, rather than leaving "Reading the document"
                      // running underneath a choice that has already been made.
                      detectSeqRef.current += 1
                      setDetecting(false)
                    }}
                  />
                )}

                {collectionTree && collectionTree.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">
                      Add to collection (optional)
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {collectionTree.map((c) => {
                        const on = selectedCollectionIds.includes(c.id)
                        return (
                          <button
                            key={c.id}
                            type="button"
                            onClick={() =>
                              setSelectedCollectionIds((prev) =>
                                on ? prev.filter((x) => x !== c.id) : [...prev, c.id],
                              )
                            }
                            className={cn(
                              "rounded-full border px-2.5 py-1 text-xs transition-colors",
                              on
                                ? "border-primary bg-primary/10 text-primary"
                                : "border-border text-muted-foreground hover:bg-accent",
                            )}
                          >
                            {c.name}
                          </button>
                        )
                      })}
                    </div>
                  </div>
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
                      <p className="mt-1 text-xs">{acceptedTypes.join(", ")}</p>
                    </div>
                  )}
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept={acceptedTypes.join(",")}
                    className="hidden"
                    onChange={handleFileChange}
                  />
                </div>

                {rejection && (
                  <div className="flex flex-col gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
                    <span>{rejection.message}</span>
                    {rejection.componentId && (
                      <InstallComponentButton componentId={rejection.componentId} />
                    )}
                  </div>
                )}

                <button
                  onClick={() => void handleUploadSubmit()}
                  disabled={!selectedFile}
                  className="w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                >
                  Add
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                <ContentTypePicker
                  value={pasteType}
                  options={contentTypeOptions}
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
                  disabled={!pasteLabel.trim() || !pasteText.trim()}
                  className="w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                >
                  Add
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
