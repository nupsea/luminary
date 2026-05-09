// VizCanvas -- the right-hand pane that holds the Sigma canvas and
// every overlay that lives above it: state overlays (no-doc-selected,
// LP/KG loading/error/empty), the optional <TagGraph> in tags mode,
// the interaction hint banner, camera controls, legend, note preview
// panel, node click popover, and edge hover tooltip.
//
// Sigma instance lifecycle is owned by the useSigma hook (called by
// the parent so it can reuse the camera handlers + canvasRef).
// Selection state (selectedNode, edgeTooltip) is also parent-owned so
// VizSidebar can consume selectedNoteId.

import type Graph from "graphology"
import { Network } from "lucide-react"
import type { Ref } from "react"

import NotePreviewPanel from "@/components/NotePreviewPanel"
import TagGraph from "@/components/TagGraph"

import { CameraControls } from "./CameraControls"
import { CanvasOverlays } from "./CanvasOverlays"
import { GraphLegend } from "./GraphLegend"
import { NodePopover } from "./NodePopover"
import type { SelectedNodeInfo, TagGraphData } from "./types"

interface VizCanvasProps {
  // Sigma host
  canvasRef: Ref<HTMLDivElement>
  filteredGraph: Graph | null
  viewMode: string
  // Tag graph
  tagGraphData: TagGraphData | undefined
  tagGraphLoading: boolean
  tagGraphError: boolean
  onTagGraphRetry: () => void
  // No-doc-selected state
  noDocSelected: boolean
  onShowAll: () => void
  // Overlay states
  lpNoInput: boolean
  lpShowLoading: boolean
  lpShowError: boolean
  lpShowEmpty: boolean
  learningPathStart: string
  onLpRetry: () => void
  kgIsLoading: boolean
  kgIsError: boolean
  showEmpty: boolean
  showAllHidden: boolean
  entityNodeCount: number
  onKgRetry: () => void
  // Camera + legend
  zoomIn: () => void
  zoomOut: () => void
  resetCamera: () => void
  showRetention: boolean
  graphStats: { typeCounts: Map<string, number> } | null
  // Selection
  selectedNoteId: string | null
  onCloseNotePreview: () => void
  selectedNode: SelectedNodeInfo | null
  onCloseNode: () => void
  lpBreadcrumb: string[]
  activeDocumentId: string | null
  onNavigate: (path: string) => void
  edgeTooltip: string | null
}

export function VizCanvas(props: VizCanvasProps) {
  const {
    canvasRef,
    filteredGraph,
    viewMode,
    tagGraphData,
    tagGraphLoading,
    tagGraphError,
    onTagGraphRetry,
    noDocSelected,
    onShowAll,
    lpNoInput,
    lpShowLoading,
    lpShowError,
    lpShowEmpty,
    learningPathStart,
    onLpRetry,
    kgIsLoading,
    kgIsError,
    showEmpty,
    showAllHidden,
    entityNodeCount,
    onKgRetry,
    zoomIn,
    zoomOut,
    resetCamera,
    showRetention,
    graphStats,
    selectedNoteId,
    onCloseNotePreview,
    selectedNode,
    onCloseNode,
    lpBreadcrumb,
    activeDocumentId,
    onNavigate,
    edgeTooltip,
  } = props

  const hasGraph = Boolean(filteredGraph && filteredGraph.order > 0)

  return (
    <div className="flex-1 relative" style={{ minWidth: 0 }}>
      {/* No-document-selected state */}
      {noDocSelected && viewMode !== "tags" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-center p-6">
          <div className="rounded-2xl bg-muted/30 p-6">
            <Network size={48} className="text-muted-foreground/30" />
          </div>
          <p className="text-lg font-semibold text-foreground">No document selected</p>
          <p className="text-sm text-muted-foreground max-w-xs">
            Switch to &ldquo;All docs&rdquo; to explore the full knowledge graph, or pick a
            document from the header.
          </p>
          <button
            onClick={onShowAll}
            className="rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors shadow-sm"
          >
            Show all documents
          </button>
        </div>
      )}

      {/* Learning path + knowledge graph state overlays */}
      <CanvasOverlays
        lpNoInput={lpNoInput}
        lpShowLoading={lpShowLoading}
        lpShowError={lpShowError}
        lpShowEmpty={lpShowEmpty}
        learningPathStart={learningPathStart}
        onLpRetry={onLpRetry}
        kgShowLoading={!noDocSelected && kgIsLoading && viewMode !== "tags"}
        kgShowError={!noDocSelected && !kgIsLoading && kgIsError && viewMode !== "tags"}
        showEmpty={showEmpty}
        showAllHidden={showAllHidden}
        entityNodeCount={entityNodeCount}
        onKgRetry={onKgRetry}
      />

      {/* Tag co-occurrence graph (S167) */}
      {viewMode === "tags" && (
        <div className="absolute inset-0">
          <TagGraph
            nodes={tagGraphData?.nodes ?? []}
            edges={tagGraphData?.edges ?? []}
            isLoading={tagGraphLoading}
            isError={tagGraphError}
            onRetry={onTagGraphRetry}
          />
        </div>
      )}

      {/* Sigma canvas */}
      <div
        ref={canvasRef}
        style={{
          width: "100%",
          height: "100%",
          display: viewMode === "tags" ? "none" : "block",
        }}
      />

      {/* Interaction hint overlay */}
      {hasGraph && (
        <div
          className="absolute top-3 left-1/2 -translate-x-1/2 z-10 pointer-events-none animate-pulse"
          style={{ animationIterationCount: 3, animationDuration: "1.5s" }}
        >
          <div className="rounded-full bg-foreground/80 px-4 py-1.5 text-[11px] font-medium text-background backdrop-blur-sm shadow-lg">
            Scroll to zoom -- Click node to explore -- Drag to pan
          </div>
        </div>
      )}

      <CameraControls
        visible={hasGraph || viewMode === "tags"}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onReset={resetCamera}
      />

      <GraphLegend
        showRetention={showRetention}
        hasGraph={hasGraph}
        typeCounts={graphStats?.typeCounts ?? null}
      />

      {/* Note node preview panel (S172) */}
      {selectedNoteId && (
        <NotePreviewPanel noteId={selectedNoteId} onClose={onCloseNotePreview} />
      )}

      {/* Node click popover */}
      {selectedNode && (
        <NodePopover
          node={selectedNode}
          viewMode={viewMode}
          lpBreadcrumb={lpBreadcrumb}
          activeDocumentId={activeDocumentId}
          onClose={onCloseNode}
          onNavigate={onNavigate}
        />
      )}

      {/* Edge hover tooltip */}
      {edgeTooltip && (
        <div className="absolute bottom-14 right-4 rounded-lg bg-foreground/90 px-3 py-1.5 text-[11px] font-medium text-background z-10 backdrop-blur-sm shadow-sm">
          {edgeTooltip.replace(/_/g, " ")}
        </div>
      )}
    </div>
  )
}
