import "@excalidraw/excalidraw/index.css"
import type {
  BinaryFiles,
  ExcalidrawImperativeAPI,
  ExcalidrawInitialDataState,
} from "@excalidraw/excalidraw/types"
import type {
  ExcalidrawElement,
  NonDeleted,
} from "@excalidraw/excalidraw/element/types"
import { Save } from "lucide-react"
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { buildExcalidrawDiagramMarkdown } from "@/lib/noteDiagrams"
import { resolveLuminaryAssetUrl, uploadNoteAsset } from "@/lib/noteAssets"

const ExcalidrawCanvas = lazy(() =>
  import("@excalidraw/excalidraw").then((mod) => ({ default: mod.Excalidraw })),
)

interface NoteDiagramDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  scenePath?: string | null
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

function sanitizeExportAppState(api: ExcalidrawImperativeAPI) {
  const appState = api.getAppState()
  return {
    ...appState,
    exportBackground: true,
    exportEmbedScene: true,
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

export function NoteDiagramDialog({ open, onOpenChange, scenePath, onSaved }: NoteDiagramDialogProps) {
  const apiRef = useRef<ExcalidrawImperativeAPI | null>(null)
  const [initialData, setInitialData] = useState<ExcalidrawInitialDataState | null>(null)
  const [sceneKey, setSceneKey] = useState(0)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return

    let cancelled = false
    async function loadScene() {
      setLoadError(null)
      apiRef.current = null
      if (!scenePath) {
        setInitialData(EMPTY_SCENE)
        setSceneKey((key) => key + 1)
        return
      }

      try {
        // Local asset URL (resolveLuminaryAssetUrl), not an API endpoint --
        // apiClient's API_BASE prefix would be wrong here.
        // eslint-disable-next-line no-restricted-syntax
        const res = await fetch(resolveLuminaryAssetUrl(scenePath))
        if (!res.ok) throw new Error(`Could not load diagram scene: ${res.status}`)
        const data = (await res.json()) as ExcalidrawInitialDataState
        if (!cancelled) {
          setInitialData({
            elements: data.elements ?? [],
            appState: {
              ...(data.appState ?? {}),
              viewBackgroundColor: data.appState?.viewBackgroundColor ?? "#ffffff",
            },
            files: data.files ?? {},
            scrollToContent: true,
          })
          setSceneKey((key) => key + 1)
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : "Could not load diagram scene")
          setInitialData(EMPTY_SCENE)
          setSceneKey((key) => key + 1)
        }
      }
    }

    void loadScene()
    return () => {
      cancelled = true
    }
  }, [open, scenePath])

  const dialogTitle = useMemo(
    () => (scenePath ? "Edit Diagram" : "New Diagram"),
    [scenePath],
  )

  async function handleSave() {
    const api = apiRef.current
    if (!api) return

    const sceneElements = [...api.getSceneElementsIncludingDeleted()]
    const elements = sceneElements.filter(isNonDeletedElement)
    if (elements.length === 0) {
      api.setToast({ message: "Add at least one item before saving." })
      return
    }

    setSaving(true)
    try {
      const { exportToSvg, serializeAsJSON } = await import("@excalidraw/excalidraw")
      const exportAppState = sanitizeExportAppState(api)
      const files = api.getFiles() as BinaryFiles
      const svg = await exportToSvg({
        elements,
        appState: exportAppState,
        files,
        exportPadding: 24,
        skipInliningFonts: true,
      })
      if (isBlankExcalidrawSvg(svg)) {
        throw new Error("Excalidraw exported an empty SVG for a non-empty diagram.")
      }
      const svgFile = new File(
        [svg.outerHTML],
        `note-diagram-${Date.now()}.svg`,
        { type: "image/svg+xml" },
      )

      const sceneJson = serializeAsJSON(
        sceneElements,
        api.getAppState(),
        files,
        "local",
      )
      const sceneFile = new File(
        [sceneJson],
        `note-diagram-${Date.now()}.excalidraw.json`,
        { type: "application/json" },
      )

      const [svgAsset, sceneAsset] = await Promise.all([
        uploadNoteAsset(svgFile),
        uploadNoteAsset(sceneFile),
      ])

      onSaved(buildExcalidrawDiagramMarkdown(svgAsset.path, sceneAsset.path))
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
      <DialogContent className="flex h-[90vh] w-[96vw] max-w-7xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b border-border px-5 py-4">
          <DialogTitle className="text-base">{dialogTitle}</DialogTitle>
          <DialogDescription className="sr-only">
            Create or edit an Excalidraw diagram for a note.
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
              Loading diagram...
            </div>
          )}
        </div>

        <DialogFooter className="border-t border-border px-5 py-3">
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
            {saving ? "Saving..." : "Save Diagram"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
