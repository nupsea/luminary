import { useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query"
import { GitBranch, Network, Tag, Zap } from "lucide-react"
import { Component, useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { ErrorInfo, ReactNode } from "react"
import Sigma from "sigma"
import type { SigmaEdgeEventPayload, SigmaNodeEventPayload } from "sigma/types"
import { useNavigate } from "react-router-dom"
import NodeHexagonProgram from "@/lib/sigma-hexagon"
import { logger } from "@/lib/logger"
import { useAppStore } from "../store"
import { useEffectiveActiveDocument } from "@/hooks/useEffectiveActiveDocument"
import { hasGraphData, isDocumentReady } from "@/lib/documentReadiness"
import { useVizStore } from "../vizStore"
import {
  ALL_ENTITY_TYPES,
  isCodeDocument,
  shouldShowClusterView,
  buildClusterNodes,
} from "@/lib/vizUtils"
import type { EntityType } from "@/lib/vizUtils"

// Type interfaces moved to pages/Viz/types.ts.
import type {
  MasteryConceptItem,
  SelectedNodeInfo,
} from "./Viz/types"

// ---------------------------------------------------------------------------
// Error boundary
// ---------------------------------------------------------------------------

class VizErrorBoundary extends Component<{ children: ReactNode }, { error: string | null }> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error.message : String(error) }
  }
  componentDidCatch(error: unknown, info: ErrorInfo) {
    logger.error("[Viz] render error", { error: String(error), componentStack: info.componentStack ?? "" })
  }
  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full items-center justify-center p-6">
          <div className="flex flex-col gap-2 rounded-md border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700 max-w-sm">
            <p className="font-medium">Graph rendering error</p>
            <p className="text-xs font-mono break-all">{this.state.error}</p>
            <button
              onClick={() => this.setState({ error: null })}
              className="self-start rounded border border-red-300 bg-white px-3 py-1 text-xs hover:bg-red-50"
            >
              Retry
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

import TagGraph from "@/components/TagGraph"
import NodeSquareProgram from "@/lib/sigma-square"
import NotePreviewPanel from "@/components/NotePreviewPanel"
// Sidebar width is set inline (260px) in the flex layout

// API fetchers moved to pages/Viz/api.ts.

// masteryColor moved to ./Viz/utils. Constants moved to ./Viz/constants.
import { masteryColor } from "./Viz/utils"
import {
  BLIND_SPOT_COLOR,
  DIAGRAM_NODE_TYPES,
  DIM_COLOR,
  LP_EDGE_COLOR,
} from "./Viz/constants"

// Core graph + DocListItem types moved to ./Viz/types.

// API helpers (fetchGraphData, fetchLearningPath, fetchDocList) moved
// to pages/Viz/api.ts.
import {
  fetchDocList,
  fetchGraphData,
  fetchLearningPath,
  fetchMasteryConcepts,
  fetchTagGraph,
} from "./Viz/api"
import {
  buildClusterGraphology,
  buildGraph,
  buildLearningPathGraph,
} from "./Viz/graphBuilders"
import { CameraControls } from "./Viz/CameraControls"
import { CanvasOverlays } from "./Viz/CanvasOverlays"
import { GraphLegend } from "./Viz/GraphLegend"
import { HeaderBar } from "./Viz/HeaderBar"
import { NodePopover } from "./Viz/NodePopover"
import { VizSidebar } from "./Viz/VizSidebar"


// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function Viz() {
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  // Effective doc: Viz needs populated graph nodes/edges. An in-progress doc
  // has none, so fall back to the user's last ready doc until ingestion lands.
  // effectiveDocumentId is optimistic during the docs query's first load so
  // the scope useState below sees the user's active book on first render.
  const { effectiveDocumentId } = useEffectiveActiveDocument({ predicate: hasGraphData })
  const activeDocumentId = effectiveDocumentId
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const mountTime = useRef(Date.now())

  // Raw sigma instance — NOT stored in React state to avoid re-render loops
  const sigmaRef = useRef<Sigma | null>(null)
  // The div that sigma renders into
  const canvasRef = useRef<HTMLDivElement>(null)

  // Entity type filter state from vizStore (persisted to localStorage) (S181)
  const { activeEntityTypes: activeTypes, toggleEntityType, selectAllEntityTypes, deselectAllEntityTypes } = useVizStore()
  const [search, setSearch] = useState("")
  // Default to "all" when no document is pre-selected so the graph loads immediately
  const [scope, setScope] = useState<"document" | "all">(activeDocumentId ? "document" : "all")

  // If the effective active doc disappears (e.g. the readiness fallback returns
  // null because no doc is currently ready), drop scope back to "all" so the
  // graph loads instead of stranding the user on "No document selected".
  useEffect(() => {
    if (!activeDocumentId) {
      setScope("all")
    }
  }, [activeDocumentId])
  // Document picker search filter state
  const [docPickerSearch, setDocPickerSearch] = useState("")
  const [docPickerOpen, setDocPickerOpen] = useState(false)
  const docPickerRef = useRef<HTMLDivElement>(null)
  const [viewMode, setViewMode] = useState<"knowledge_graph" | "call_graph" | "learning_path" | "tags">("knowledge_graph")
  const [selectedNode, setSelectedNode] = useState<SelectedNodeInfo | null>(null)
  const [edgeTooltip, setEdgeTooltip] = useState<string | null>(null)
  // Diagrams layer toggle: show/hide diagram-derived nodes (S136)
  const [showDiagramNodes, setShowDiagramNodes] = useState(true)
  // Prerequisites layer toggle: show/hide PREREQUISITE_OF edges (S139)
  const [showPrerequisites, setShowPrerequisites] = useState(true)
  // Cross-book layer toggle: show/hide SAME_CONCEPT edges (S141) -- default off (noisy)
  const [showCrossBook, setShowCrossBook] = useState(false)
  // Notes layer toggle: show/hide Note nodes (S172) -- default off
  const [showNotes, setShowNotes] = useState(false)
  // Retention overlay toggle: color nodes by FSRS mastery strength
  const [showRetention, setShowRetention] = useState(false)
  // Selected note node ID for NotePreviewPanel (S172)
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null)
  // Learning path state (S117)
  const [learningPathStart, setLearningPathStart] = useState("")
  const [lpInputDraft, setLpInputDraft] = useState("")
  // (View options are always visible in the sidebar; no collapse state needed)
  // Cluster view toggle (S181): when enabled and entity count > 200, collapse into type clusters
  const [clusterViewEnabled, setClusterViewEnabled] = useState(false)
  // Set of entity types that have been expanded out of cluster view by clicking a cluster node
  const [expandedClusters, setExpandedClusters] = useState<Set<string>>(new Set())

  // Document list for the picker
  const { data: docList } = useQuery({
    queryKey: ["viz-doc-list"],
    queryFn: fetchDocList,
    staleTime: 30_000,
  })

  // Filtered doc list for the searchable picker. In-progress docs are
  // intentionally hidden -- their graph is empty and selecting them would do
  // nothing. The library is the only surface that exposes them.
  const filteredDocList = useMemo(() => {
    if (!docList) return []
    const ready = docList.filter(hasGraphData)
    if (!docPickerSearch.trim()) return ready
    const q = docPickerSearch.toLowerCase()
    return ready.filter((d) => d.title.toLowerCase().includes(q))
  }, [docList, docPickerSearch])

  // Close doc picker on outside click
  useEffect(() => {
    if (!docPickerOpen) return
    function handleClick(e: MouseEvent) {
      if (docPickerRef.current && !docPickerRef.current.contains(e.target as Node)) {
        setDocPickerOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [docPickerOpen])

  // Handle document selection from the searchable picker
  const handleDocSelect = useCallback((docId: string | null) => {
    setActiveDocument(docId)
    setDocPickerOpen(false)
    setDocPickerSearch("")
    setSearch("") // Clear the graph visual filter as well so the new doc is fully visible
    setSelectedNode(null)
    setSelectedNoteId(null)
    
    // Auto-switch scope: selecting a doc → "This doc", clearing → "All docs"
    if (docId) {
      setScope("document")
    } else {
      setScope("all")
    }
  }, [setActiveDocument])

  // Detect whether selected document is a code document (S181)
  const selectedDoc = docList?.find((d) => d.id === activeDocumentId)
  const isCodeDoc = isCodeDocument(selectedDoc?.format ?? "")

  const noDocSelected = scope === "document" && !activeDocumentId

  const queryKey = ["graph", scope, activeDocumentId, viewMode, showCrossBook, showNotes]
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey,
    queryFn: () => fetchGraphData(
      activeDocumentId,
      scope,
      viewMode as "knowledge_graph" | "call_graph",
      showCrossBook,
      showNotes,
    ),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
    enabled: !noDocSelected && viewMode !== "learning_path" && viewMode !== "tags",
  })

  // Learning path query (S117)
  const {
    data: lpData,
    isLoading: lpLoading,
    isError: lpError,
    refetch: lpRefetch,
  } = useQuery({
    queryKey: ["learning-path", activeDocumentId, learningPathStart],
    queryFn: () => fetchLearningPath(activeDocumentId!, learningPathStart),
    staleTime: 30_000,
    enabled: viewMode === "learning_path" && !!activeDocumentId && !!learningPathStart,
  })

  // Tag graph query (S167)
  const {
    data: tagGraphData,
    isLoading: tagGraphLoading,
    isError: tagGraphError,
    refetch: tagGraphRefetch,
  } = useQuery({
    queryKey: ["tag-graph"],
    queryFn: fetchTagGraph,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
    enabled: viewMode === "tags",
  })

  // Mastery / retention overlay data. Limit to ready docs so an in-progress
  // ingestion (no graph yet) doesn't drag down the all-docs query.
  const allDocIds = useMemo(
    () => docList?.filter(isDocumentReady).map((d) => d.id) ?? [],
    [docList],
  )
  const masteryDocIds = useMemo(
    () => (scope === "document" && activeDocumentId ? [activeDocumentId] : allDocIds),
    [scope, activeDocumentId, allDocIds],
  )
  const { data: masteryData } = useQuery({
    queryKey: ["mastery-concepts", ...masteryDocIds],
    queryFn: () => fetchMasteryConcepts(masteryDocIds),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
    enabled: showRetention && masteryDocIds.length > 0 && viewMode !== "tags",
  })
  // Build lowercase name -> mastery entry map for fast lookup in nodeReducer
  const masteryMap = useMemo(() => {
    const map = new Map<string, MasteryConceptItem>()
    if (!masteryData?.concepts) return map
    for (const c of masteryData.concepts) {
      map.set(c.concept.toLowerCase(), c)
    }
    return map
  }, [masteryData])

  // Reset call_graph mode when the selected document is no longer a code document (S181)
  useEffect(() => {
    if (viewMode === "call_graph" && !isCodeDoc) {
      setViewMode("knowledge_graph")
    }
  }, [isCodeDoc, viewMode])

  useEffect(() => {
    if (!isLoading && data) {
      logger.info("[Viz] loaded", {
        duration_ms: Date.now() - mountTime.current,
        nodes: data.nodes.length,
      })
    }
  }, [isLoading, data])

  // Build filtered graphology graph from API data + active entity types (or learning path)
  // Not used for "tags" mode -- TagGraph component builds its own graphology instance.
  const filteredGraph = useMemo(() => {
    if (viewMode === "tags") return null
    if (viewMode === "learning_path") {
      if (!lpData || lpData.nodes.length === 0) return null
      return buildLearningPathGraph(lpData)
    }
    if (!data) return null
    const visibleNodes = data.nodes.filter((n) => {
      // Note nodes (S172): controlled by showNotes toggle, independent of entity type filter
      if (n.type === "note") return showNotes
      if (DIAGRAM_NODE_TYPES.has(n.type)) {
        // Diagram nodes are hidden when showDiagramNodes=false OR type not in activeTypes
        return showDiagramNodes && activeTypes.has(n.type as EntityType)
      }
      return activeTypes.has(n.type as EntityType)
    })
    const visibleIds = new Set(visibleNodes.map((n) => n.id))
    const visibleEdges = data.edges.filter(
      (e) =>
        visibleIds.has(e.source) &&
        visibleIds.has(e.target) &&
        (showPrerequisites || e.relation !== "PREREQUISITE_OF") &&
        (showCrossBook || e.relation !== "SAME_CONCEPT"),
    )
    // Cluster view (S181): when enabled and non-note entity count > 200
    if (shouldShowClusterView(visibleNodes, clusterViewEnabled)) {
      const clusterDefs = buildClusterNodes(visibleNodes, expandedClusters)
      return buildClusterGraphology(visibleNodes, visibleEdges, clusterDefs, expandedClusters)
    }
    return buildGraph(visibleNodes, visibleEdges)
  }, [data, activeTypes, viewMode, lpData, showDiagramNodes, showPrerequisites, showCrossBook, showNotes, clusterViewEnabled, expandedClusters])

  // ---------------------------------------------------------------------------
  // Core effect: mount/update raw Sigma instance when filteredGraph changes
  // ---------------------------------------------------------------------------

  // Track whether we need to rebuild sigma after a WebGL context restore
  const pendingRestoreRef = useRef(false)

  useEffect(() => {
    const el = canvasRef.current
    if (!el) return

    // Keep previous sigma alive during loading transitions (filteredGraph = null)
    if (!filteredGraph) return
    
    // Destroy previous instance
    if (sigmaRef.current) {
      sigmaRef.current.kill()
      sigmaRef.current = null
    }

    if (filteredGraph.order === 0) {
      el.innerHTML = ""
      return
    }

    // Delay initialization slightly to ensure WebGL context from killed instance is fully reclaimed
    const timer = setTimeout(() => {
      // Re-check el exists in timeout
      const currentEl = canvasRef.current
      if (!currentEl) return

      // Clean container explicitly
      currentEl.innerHTML = ""

      const s = new Sigma(filteredGraph, currentEl, {
        renderEdgeLabels: false,
        defaultEdgeColor: viewMode === "learning_path" ? LP_EDGE_COLOR : "#e2e8f0",
        labelSize: 12,
        labelWeight: "normal",
        nodeProgramClasses: {
          hexagon: NodeHexagonProgram as any,
          square: NodeSquareProgram as any,
        },
        allowInvalidContainer: true,
      })

      // WebGL context lost/restored handlers
      const canvases = currentEl.querySelectorAll("canvas")
      const handleContextLost = (e: Event) => {
        e.preventDefault()
        logger.warn("[Viz] WebGL context lost -- will restore on recovery")
        pendingRestoreRef.current = true
      }
      const handleContextRestored = () => {
        logger.info("[Viz] WebGL context restored -- refreshing sigma")
        pendingRestoreRef.current = false
        try { s.refresh() } catch { logger.warn("[Viz] sigma refresh failed") }
      }
      canvases.forEach((c) => {
        c.addEventListener("webglcontextlost", handleContextLost)
        c.addEventListener("webglcontextrestored", handleContextRestored)
      })

      s.on("clickNode", (payload: SigmaNodeEventPayload) => {
        const { node, event } = payload
        const entityType = filteredGraph.getNodeAttribute(node, "entityType") as string

        const isCluster = filteredGraph.getNodeAttribute(node, "isCluster") as boolean | undefined
        if (isCluster) {
          const clusterEntityType = filteredGraph.getNodeAttribute(node, "clusterEntityType") as string
          setExpandedClusters((prev) => {
            const next = new Set(prev)
            if (next.has(clusterEntityType)) next.delete(clusterEntityType)
            else next.add(clusterEntityType)
            return next
          })
          event.preventSigmaDefault()
          return
        }

        if (entityType === "note") {
          const noteId = (filteredGraph.getNodeAttribute(node, "note_id") as string | undefined) ?? node
          setSelectedNode(null)
          setSelectedNoteId(noteId)
          event.preventSigmaDefault()
          return
        }

        const pos = s.graphToViewport({
          x: filteredGraph.getNodeAttribute(node, "x") as number,
          y: filteredGraph.getNodeAttribute(node, "y") as number,
        })
        const rect = currentEl.getBoundingClientRect()
        setSelectedNoteId(null)
        setSelectedNode({
          id: node,
          label: filteredGraph.getNodeAttribute(node, "label") as string,
          type: entityType,
          frequency: filteredGraph.getNodeAttribute(node, "frequency") as number,
          screenX: rect.left + pos.x,
          screenY: rect.top + pos.y,
          source_image_id: (filteredGraph.getNodeAttribute(node, "source_image_id") as string | undefined) ?? "",
        })
        event.preventSigmaDefault()
      })

      s.on("enterEdge", (payload: SigmaEdgeEventPayload) => {
        const edgeType = (filteredGraph.getEdgeAttribute(payload.edge, "type") as string | undefined) ?? "CO_OCCURS"
        setEdgeTooltip(edgeType)
      })
      s.on("leaveEdge", () => setEdgeTooltip(null))

      s.on("clickStage", () => {
        setSelectedNode(null)
        setSelectedNoteId(null)
      })

      sigmaRef.current = s
    }, 100)

    return () => {
      clearTimeout(timer)
      if (sigmaRef.current) {
        sigmaRef.current.kill()
        sigmaRef.current = null
      }
      if (el) el.innerHTML = ""
    }
  }, [filteredGraph])

  // ---------------------------------------------------------------------------
  // Combined search + retention overlay effect
  // Both use sigma nodeReducer so they must be composed in a single effect.
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const s = sigmaRef.current
    if (!s) return

    const q = search?.toLowerCase() ?? ""
    const hasSearch = q.length > 0
    const hasRetention = showRetention && masteryMap.size > 0

    if (!hasSearch && !hasRetention) {
      s.setSetting("nodeReducer", null)
      s.setSetting("edgeReducer", null)
      return
    }

    s.setSetting("nodeReducer", (_node: string, d: Record<string, unknown>) => {
      const label = ((d.label as string) ?? "")
      const labelLower = label.toLowerCase()

      // Search dimming takes priority
      if (hasSearch && !labelLower.includes(q)) {
        return { ...d, color: DIM_COLOR, label: "" }
      }

      // Retention coloring (skip note/cluster nodes)
      if (hasRetention) {
        const entityType = d.entityType as string
        if (entityType === "note" || entityType === "cluster") return d
        const entry = masteryMap.get(labelLower)
        if (!entry || entry.no_flashcards) {
          return { ...d, color: BLIND_SPOT_COLOR }
        }
        return { ...d, color: masteryColor(entry.mastery) }
      }

      return d
    })

    s.setSetting("edgeReducer", hasSearch
      ? (_edge: string, d: Record<string, unknown>) => ({ ...d, color: DIM_COLOR })
      : null,
    )

    // Pan to first matching node on search
    if (hasSearch) {
      const graph = s.getGraph()
      const firstMatch = graph.nodes().find((n) => {
        const lbl = (graph.getNodeAttribute(n, "label") as string) ?? ""
        return lbl.toLowerCase().includes(q)
      })
      if (firstMatch) {
        s.getCamera().animate(
          {
            x: graph.getNodeAttribute(firstMatch, "x") as number,
            y: graph.getNodeAttribute(firstMatch, "y") as number,
            ratio: 0.5,
          },
          { duration: 500 },
        )
      }
    }
  }, [search, filteredGraph, showRetention, masteryMap]) // re-apply after sigma rebuilds

  // ---------------------------------------------------------------------------
  // Camera controls
  // ---------------------------------------------------------------------------
  const zoomIn = () => {
    const s = sigmaRef.current
    if (!s) return
    s.getCamera().animate({ ratio: s.getCamera().ratio / 1.5 }, { duration: 300 })
  }
  const zoomOut = () => {
    const s = sigmaRef.current
    if (!s) return
    s.getCamera().animate({ ratio: s.getCamera().ratio * 1.5 }, { duration: 300 })
  }
  const resetCamera = () => {
    sigmaRef.current?.getCamera().animate(
      { x: 0.5, y: 0.5, ratio: 1, angle: 0 },
      { duration: 300 },
    )
  }

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------
  const showEmpty =
    !noDocSelected &&
    !isLoading &&
    !isError &&
    (!data || data.nodes.length === 0) &&
    viewMode !== "learning_path" &&
    viewMode !== "tags"
  // showAllHidden: only considers entity/diagram nodes; note nodes (S172) are separate
  const entityNodeCount = data ? data.nodes.filter((n) => n.type !== "note").length : 0
  const showAllHidden =
    filteredGraph !== null &&
    filteredGraph.order === 0 &&
    !!data &&
    entityNodeCount > 0 &&
    viewMode !== "learning_path" &&
    viewMode !== "tags"

  // Learning path render helpers (S117)
  const lpNoInput = viewMode === "learning_path" && !learningPathStart
  const lpShowLoading = viewMode === "learning_path" && !!learningPathStart && lpLoading
  const lpShowError = viewMode === "learning_path" && !!learningPathStart && !lpLoading && lpError
  const lpShowEmpty = viewMode === "learning_path" && !!learningPathStart && !lpLoading && !lpError && lpData && lpData.nodes.length === 0

  // Learning path prerequisites breadcrumb for selected node
  const lpBreadcrumb = useMemo((): string[] => {
    if (!selectedNode || !lpData || viewMode !== "learning_path") return []
    // Walk edges from selectedNode back toward start
    const trail: string[] = [selectedNode.label]
    const edgeMap: Record<string, string> = {}
    lpData.edges.forEach((e) => { edgeMap[e.from_entity] = e.to_entity })
    let current = selectedNode.label
    const seen = new Set<string>([current])
    while (edgeMap[current] && !seen.has(edgeMap[current])) {
      current = edgeMap[current]
      seen.add(current)
      trail.push(current)
    }
    return trail
  }, [selectedNode, lpData, viewMode])

  // Derived stats for the graph legend
  const graphStats = useMemo(() => {
    if (viewMode === "tags") return null
    if (!filteredGraph || filteredGraph.order === 0) return null
    const nodeCount = filteredGraph.order
    const edgeCount = filteredGraph.size
    // Count unique entity types present
    const typeCounts = new Map<string, number>()
    filteredGraph.forEachNode((_node, attrs) => {
      const t = (attrs.entityType as string) ?? "unknown"
      typeCounts.set(t, (typeCounts.get(t) ?? 0) + 1)
    })
    return { nodeCount, edgeCount, typeCounts }
  }, [filteredGraph, viewMode])

  // View mode configuration
  const viewModes = useMemo(() => {
    const modes: { key: typeof viewMode; label: string; icon: typeof Network }[] = [
      { key: "knowledge_graph", label: "Knowledge", icon: Network },
      ...(isCodeDoc ? [{ key: "call_graph" as const, label: "Call Graph", icon: GitBranch }] : []),
      { key: "learning_path", label: "Learning Path", icon: Zap },
      { key: "tags", label: "Tags", icon: Tag },
    ]
    return modes
  }, [isCodeDoc])

  return (
    <VizErrorBoundary>
      <div className="flex h-full flex-col bg-background" style={{ height: "100vh", overflow: "hidden" }}>

        <HeaderBar
          viewModes={viewModes}
          viewMode={viewMode}
          onSelectViewMode={(key) => {
            setViewMode(key as typeof viewMode)
            void queryClient.invalidateQueries({ queryKey })
          }}
          scope={scope}
          onSelectScope={(s) => {
            setScope(s)
            void queryClient.invalidateQueries({ queryKey })
          }}
          graphStats={graphStats}
        />

        {/* ---- Main content: sidebar + graph canvas ---- */}
        <div className="flex flex-1 overflow-hidden" style={{ minHeight: 0 }}>
          <VizSidebar
            viewMode={viewMode}
            docPickerSearch={docPickerSearch}
            onDocPickerSearchChange={setDocPickerSearch}
            onClearGlobalSearch={() => setSearch("")}
            activeDocumentId={activeDocumentId}
            onDocSelect={handleDocSelect}
            filteredDocList={filteredDocList}
            showNotes={showNotes}
            filteredGraph={filteredGraph}
            selectedNoteId={selectedNoteId}
            onSelectNoteId={setSelectedNoteId}
            onClearSelectedNode={() => setSelectedNode(null)}
            lpInputDraft={lpInputDraft}
            onLpInputDraftChange={setLpInputDraft}
            onSetLearningPathStart={setLearningPathStart}
            showDiagramNodes={showDiagramNodes}
            setShowDiagramNodes={setShowDiagramNodes}
            showPrerequisites={showPrerequisites}
            setShowPrerequisites={setShowPrerequisites}
            showCrossBook={showCrossBook}
            setShowCrossBook={setShowCrossBook}
            setShowNotes={setShowNotes}
            showRetention={showRetention}
            setShowRetention={setShowRetention}
            masteryData={masteryData}
            onSetSearch={setSearch}
            allEntityTypes={ALL_ENTITY_TYPES}
            activeTypes={activeTypes}
            onToggleEntityType={toggleEntityType}
            onSelectAllEntityTypes={selectAllEntityTypes}
            onDeselectAllEntityTypes={deselectAllEntityTypes}
            clusterViewEnabled={clusterViewEnabled}
            setClusterViewEnabled={setClusterViewEnabled}
          />

          {/* ---- Graph area ---- */}
          <div className="flex-1 relative" style={{ minWidth: 0 }}>
            {/* State overlays */}

            {noDocSelected && viewMode !== "tags" && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-center p-6">
                <div className="rounded-2xl bg-muted/30 p-6">
                  <Network size={48} className="text-muted-foreground/30" />
                </div>
                <p className="text-lg font-semibold text-foreground">No document selected</p>
                <p className="text-sm text-muted-foreground max-w-xs">
                  Switch to &ldquo;All docs&rdquo; to explore the full knowledge graph, or pick a document from the header.
                </p>
                <button
                  onClick={() => setScope("all")}
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
              lpShowEmpty={Boolean(lpShowEmpty)}
              learningPathStart={learningPathStart}
              onLpRetry={() => void lpRefetch()}
              kgShowLoading={!noDocSelected && isLoading && viewMode !== "tags"}
              kgShowError={!noDocSelected && !isLoading && isError && viewMode !== "tags"}
              showEmpty={showEmpty}
              showAllHidden={showAllHidden}
              entityNodeCount={entityNodeCount}
              onKgRetry={() => void refetch()}
            />

            {/* Tag co-occurrence graph (S167) */}
            {viewMode === "tags" && (
              <div className="absolute inset-0">
                <TagGraph
                  nodes={tagGraphData?.nodes ?? []}
                  edges={tagGraphData?.edges ?? []}
                  isLoading={tagGraphLoading}
                  isError={tagGraphError}
                  onRetry={() => void tagGraphRefetch()}
                />
              </div>
            )}

            {/* Sigma canvas */}
            <div
              ref={canvasRef}
              style={{ width: "100%", height: "100%", display: viewMode === "tags" ? "none" : "block" }}
            />

            {/* Interaction hint overlay */}
            {filteredGraph && filteredGraph.order > 0 && (
              <div
                className="absolute top-3 left-1/2 -translate-x-1/2 z-10 pointer-events-none animate-pulse"
                style={{ animationIterationCount: 3, animationDuration: "1.5s" }}
              >
                <div className="rounded-full bg-foreground/80 px-4 py-1.5 text-[11px] font-medium text-background backdrop-blur-sm shadow-lg">
                  Scroll to zoom  --  Click node to explore  --  Drag to pan
                </div>
              </div>
            )}

            {/* Camera controls (bottom-right) */}
            <CameraControls
              visible={
                Boolean(filteredGraph && filteredGraph.order > 0) || viewMode === "tags"
              }
              onZoomIn={zoomIn}
              onZoomOut={zoomOut}
              onReset={resetCamera}
            />

            {/* Graph legend (bottom-left) -- switches between entity types and retention */}
            <GraphLegend
              showRetention={showRetention}
              hasGraph={Boolean(filteredGraph && filteredGraph.order > 0)}
              typeCounts={graphStats?.typeCounts ?? null}
            />

            {/* Note node preview panel (S172) */}
            {selectedNoteId && (
              <NotePreviewPanel
                noteId={selectedNoteId}
                onClose={() => setSelectedNoteId(null)}
              />
            )}

            {/* Node click popover */}
            {selectedNode && (
              <NodePopover
                node={selectedNode}
                viewMode={viewMode}
                lpBreadcrumb={lpBreadcrumb}
                activeDocumentId={activeDocumentId}
                onClose={() => setSelectedNode(null)}
                onNavigate={(p) => navigate(p)}
              />
            )}

            {/* Edge hover tooltip */}
            {edgeTooltip && (
              <div className="absolute bottom-14 right-4 rounded-lg bg-foreground/90 px-3 py-1.5 text-[11px] font-medium text-background z-10 backdrop-blur-sm shadow-sm">
                {edgeTooltip.replace(/_/g, " ")}
              </div>
            )}
          </div>
        </div>
      </div>
    </VizErrorBoundary>
  )
}
