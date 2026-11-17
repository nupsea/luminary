import "@excalidraw/excalidraw/index.css"
import type {
  AppState,
  BinaryFileData,
  BinaryFiles,
  DataURL,
  ExcalidrawImperativeAPI,
  ExcalidrawInitialDataState,
} from "@excalidraw/excalidraw/types"
import type {
  ExcalidrawElement,
  FileId,
  NonDeleted,
} from "@excalidraw/excalidraw/element/types"
import { ArrowUpRight, Highlighter, PenLine, Save, Type, type LucideIcon } from "lucide-react"
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  ANNOTATED_IMAGE_LABEL,
  DIAGRAM_LABEL,
  buildExcalidrawDiagramMarkdown,
  fitAnnotationImage,
  type ImageSize,
} from "@/lib/noteDiagrams"
import { resolveLuminaryAssetUrl, uploadNoteAsset } from "@/lib/noteAssets"
import { cn } from "@/lib/utils"

const ExcalidrawCanvas = lazy(() =>
  import("@excalidraw/excalidraw").then((mod) => ({ default: mod.Excalidraw })),
)

interface NoteDiagramDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  scenePath?: string | null
  /** A note image to annotate: it becomes the locked bottom layer of a new scene. */
  imagePath?: string | null
  /** Saves as an annotated image rather than a diagram, with the annotation tools shown. */
  annotated?: boolean
  /** The display size the saved markdown keeps; null keeps none, omitted means large. */
  size?: ImageSize | null
  onSaved: (markdown: string) => void
}

const EMPTY_SCENE: ExcalidrawInitialDataState = {
  elements: [],
  appState: {
    viewBackgroundColor: "#ffffff",
  },
  files: {},
  scrollToContent: true,
}

const ANNOTATION_RED = "#e03131"

// Helvetica is a system font: the SVG is shown through <img>, which loads no web fonts.
const HELVETICA = 2

type AnnotationStyle = Pick<
  AppState,
  | "currentItemStrokeColor"
  | "currentItemBackgroundColor"
  | "currentItemFillStyle"
  | "currentItemOpacity"
  | "currentItemRoughness"
  | "currentItemRoundness"
  | "currentItemStrokeWidth"
  | "currentItemFontFamily"
>

const ANNOTATION_STYLE: AnnotationStyle = {
  currentItemStrokeColor: ANNOTATION_RED,
  currentItemBackgroundColor: "transparent",
  currentItemFillStyle: "solid",
  currentItemOpacity: 100,
  currentItemRoughness: 0,
  currentItemRoundness: "round",
  currentItemStrokeWidth: 2,
  currentItemFontFamily: HELVETICA,
}

type AnnotationToolType = "rectangle" | "freedraw" | "arrow" | "text"

interface AnnotationTool {
  label: string
  icon: LucideIcon
  tool: AnnotationToolType
  style: Partial<AnnotationStyle>
}

const ANNOTATION_TOOLS: AnnotationTool[] = [
  {
    label: "Highlight",
    icon: Highlighter,
    tool: "rectangle",
    style: {
      currentItemStrokeColor: "transparent",
      currentItemBackgroundColor: "#ffd43b",
      currentItemFillStyle: "solid",
      currentItemOpacity: 40,
      currentItemRoundness: "sharp",
    },
  },
  { label: "Pen", icon: PenLine, tool: "freedraw", style: {} },
  { label: "Arrow", icon: ArrowUpRight, tool: "arrow", style: {} },
  { label: "Text", icon: Type, tool: "text", style: {} },
]

function sanitizeExportAppState(api: ExcalidrawImperativeAPI, annotated: boolean) {
  const appState = api.getAppState()
  return {
    ...appState,
    exportBackground: true,
    // The scene is saved beside the SVG; embedding it again would carry the snapshot twice.
    exportEmbedScene: !annotated,
    exportWithDarkMode: false,
    viewBackgroundColor: appState.viewBackgroundColor || "#ffffff",
  }
}

function isNonDeletedElement(element: ExcalidrawElement): element is NonDeleted<ExcalidrawElement> {
  return !element.isDeleted
}

function isBlankExcalidrawSvg(svg: SVGSVGElement) {
  return svg.getAttribute("viewBox") === "0 0 20 20" && !svg.querySelector("g, path, text, image")
}

function readAsDataURL(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error ?? new Error("Could not read the image"))
    reader.readAsDataURL(blob)
  })
}

function naturalSize(dataURL: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight })
    img.onerror = () => reject(new Error("Could not decode the image"))
    img.src = dataURL
  })
}

async function loadAnnotationScene(imagePath: string): Promise<ExcalidrawInitialDataState> {
  // Local asset URL, not an API endpoint -- apiClient's prefix would be wrong here.
  // no-store: the note's <img> cached this response without CORS headers (no Vary: Origin).
  // eslint-disable-next-line no-restricted-syntax
  const res = await fetch(resolveLuminaryAssetUrl(imagePath), { cache: "no-store" })
  if (!res.ok) throw new Error(`Could not load the image: ${res.status}`)
  const blob = await res.blob()
  const dataURL = await readAsDataURL(blob)
  const natural = await naturalSize(dataURL)
  const fitted = fitAnnotationImage(natural.width, natural.height)
  const { convertToExcalidrawElements } = await import("@excalidraw/excalidraw")
  const fileId = `snapshot-${Date.now()}` as FileId
  const elements = convertToExcalidrawElements([
    { type: "image", fileId, x: 0, y: 0, ...fitted, locked: true, status: "saved" },
  ])
  const file: BinaryFileData = {
    id: fileId,
    dataURL: dataURL as DataURL,
    mimeType: (blob.type || "image/png") as BinaryFileData["mimeType"],
    created: Date.now(),
  }
  return {
    elements,
    appState: { viewBackgroundColor: "#ffffff", ...ANNOTATION_STYLE },
    files: { [fileId]: file },
    scrollToContent: true,
  }
}

async function loadSavedScene(scenePath: string): Promise<ExcalidrawInitialDataState> {
  // eslint-disable-next-line no-restricted-syntax
  const res = await fetch(resolveLuminaryAssetUrl(scenePath))
  if (!res.ok) throw new Error(`Could not load diagram scene: ${res.status}`)
  const data = (await res.json()) as ExcalidrawInitialDataState
  return {
    elements: data.elements ?? [],
    appState: {
      ...(data.appState ?? {}),
      viewBackgroundColor: data.appState?.viewBackgroundColor ?? "#ffffff",
    },
    files: data.files ?? {},
    scrollToContent: true,
  }
}

export function NoteDiagramDialog({
  open,
  onOpenChange,
  scenePath,
  imagePath,
  annotated = Boolean(imagePath),
  size,
  onSaved,
}: NoteDiagramDialogProps) {
  const apiRef = useRef<ExcalidrawImperativeAPI | null>(null)
  const [initialData, setInitialData] = useState<ExcalidrawInitialDataState | null>(null)
  const [sceneKey, setSceneKey] = useState(0)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [activeTool, setActiveTool] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return

    let cancelled = false
    async function loadScene() {
      setLoadError(null)
      setActiveTool(null)
      setInitialData(null)
      apiRef.current = null
      try {
        const data = scenePath
          ? await loadSavedScene(scenePath)
          : imagePath
            ? await loadAnnotationScene(imagePath)
            : EMPTY_SCENE
        if (!cancelled) {
          setInitialData(data)
          setSceneKey((key) => key + 1)
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : "Could not load the drawing")
          // An image that failed to load leaves nothing to annotate.
          if (!imagePath || scenePath) {
            setInitialData(EMPTY_SCENE)
            setSceneKey((key) => key + 1)
          }
        }
      }
    }

    void loadScene()
    return () => {
      cancelled = true
    }
  }, [open, scenePath, imagePath])

  const dialogTitle = useMemo(() => {
    if (annotated) return scenePath ? "Edit Annotated Image" : "Annotate Image"
    return scenePath ? "Edit Diagram" : "New Diagram"
  }, [annotated, scenePath])

  function selectAnnotationTool(preset: AnnotationTool) {
    const api = apiRef.current
    if (!api) return
    api.updateScene({ appState: { ...ANNOTATION_STYLE, ...preset.style } })
    api.setActiveTool({ type: preset.tool })
    setActiveTool(preset.label)
  }

  async function handleSave() {
    const api = apiRef.current
    if (!api) return

    const sceneElements = [...api.getSceneElementsIncludingDeleted()]
    const elements = sceneElements.filter(isNonDeletedElement)
    const drawn = annotated ? elements.filter((element) => element.type !== "image") : elements
    if (drawn.length === 0) {
      api.setToast({
        message: annotated ? "Mark up the image before saving." : "Add at least one item before saving.",
      })
      return
    }

    setSaving(true)
    try {
      const { exportToSvg, serializeAsJSON } = await import("@excalidraw/excalidraw")
      const exportAppState = sanitizeExportAppState(api, annotated)
      const files = api.getFiles() as BinaryFiles
      const svg = await exportToSvg({
        elements,
        appState: exportAppState,
        files,
        exportPadding: annotated ? 8 : 24,
        skipInliningFonts: true,
      })
      if (isBlankExcalidrawSvg(svg)) {
        throw new Error("Excalidraw exported an empty SVG for a non-empty diagram.")
      }
      const stamp = Date.now()
      const svgFile = new File([svg.outerHTML], `note-diagram-${stamp}.svg`, {
        type: "image/svg+xml",
      })

      const sceneJson = serializeAsJSON(sceneElements, api.getAppState(), files, "local")
      const sceneFile = new File([sceneJson], `note-diagram-${stamp}.excalidraw.json`, {
        type: "application/json",
      })

      const [svgAsset, sceneAsset] = await Promise.all([
        uploadNoteAsset(svgFile),
        uploadNoteAsset(sceneFile),
      ])

      onSaved(
        buildExcalidrawDiagramMarkdown(
          svgAsset.path,
          sceneAsset.path,
          annotated ? ANNOTATED_IMAGE_LABEL : DIAGRAM_LABEL,
          size,
        ),
      )
      onOpenChange(false)
    } catch (err) {
      api.setToast({
        message: err instanceof Error ? err.message : "Could not save diagram.",
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="flex h-[90vh] w-[96vw] max-w-7xl flex-col gap-0 overflow-hidden p-0"
        // Excalidraw uses Escape to leave text editing and deselect; only Cancel discards the drawing.
        onEscapeKeyDown={(event) => event.preventDefault()}
        onInteractOutside={(event) => event.preventDefault()}
      >
        <DialogHeader className="border-b border-border px-5 py-4">
          <DialogTitle className="text-base">{dialogTitle}</DialogTitle>
          <DialogDescription className="sr-only">
            {annotated
              ? "Highlight, draw on or add text to a note image."
              : "Create or edit an Excalidraw diagram for a note."}
          </DialogDescription>
          {loadError && <p className="text-xs text-amber-600">{loadError}</p>}
        </DialogHeader>

        <div className="min-h-0 flex-1 bg-background">
          {initialData ? (
            <Suspense
              fallback={
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  Loading editor...
                </div>
              }
            >
              <ExcalidrawCanvas
                key={sceneKey}
                initialData={initialData}
                excalidrawAPI={(api) => {
                  apiRef.current = api
                }}
                onChange={(_elements, appState) => {
                  // Excalidraw's own toolbar, or the end of a stroke, can change the tool.
                  setActiveTool((label) =>
                    ANNOTATION_TOOLS.some(
                      (preset) => preset.label === label && preset.tool === appState.activeTool.type,
                    )
                      ? label
                      : null,
                  )
                }}
                UIOptions={{
                  canvasActions: {
                    loadScene: false,
                    saveAsImage: false,
                  },
                }}
              />
            </Suspense>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              {loadError ? "Nothing to annotate." : annotated ? "Loading image..." : "Loading diagram..."}
            </div>
          )}
        </div>

        <DialogFooter className="border-t border-border px-5 py-3 sm:justify-between">
          {annotated ? (
            <div className="flex items-center gap-1" role="toolbar" aria-label="Annotation tools">
              {ANNOTATION_TOOLS.map((preset) => (
                <button
                  key={preset.label}
                  type="button"
                  onClick={() => selectAnnotationTool(preset)}
                  disabled={!initialData}
                  aria-pressed={activeTool === preset.label}
                  className={cn(
                    "flex items-center gap-1.5 rounded border border-border px-2.5 py-1.5 text-xs hover:bg-accent disabled:opacity-50",
                    activeTool === preset.label && "border-primary bg-primary/10 text-primary",
                  )}
                >
                  <preset.icon size={13} />
                  {preset.label}
                </button>
              ))}
            </div>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving || !initialData}
              className="flex items-center gap-1.5 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
            >
              <Save size={13} />
              {saving ? "Saving..." : annotated ? "Save Annotations" : "Save Diagram"}
            </button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
