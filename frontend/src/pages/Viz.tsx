import { useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query"
import Graph from "graphology"
import forceAtlas2 from "graphology-layout-forceatlas2"
import {
  AlertTriangle,
  BookOpen,
  Eye,
  FileText,
  Filter,
  GitBranch,
  Library,
  Maximize2,
  Minus,
  Network,
  Plus,
  Search,
  StickyNote,
  Tag,
  X,
  Zap,
} from "lucide-react"
import { Component, useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { ErrorInfo, ReactNode } from "react"
import Sigma from "sigma"
import type { SigmaEdgeEventPayload, SigmaNodeEventPayload } from "sigma/types"
import { useNavigate } from "react-router-dom"
import { Skeleton } from "@/components/ui/skeleton"
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
import type { EntityType, ClusterNodeDef } from "@/lib/vizUtils"

// Type interfaces moved to pages/Viz/types.ts.
import type {
  DocListItem,
  GraphData,
  GraphEdge,
  GraphNode,
  LearningPathData,
  LearningPathNode,
  MasteryConceptItem,
  MasteryConceptsResponse,
  SelectedNodeInfo,
  TagGraphData,
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

import { API_BASE } from "@/lib/config"
import TagGraph from "@/components/TagGraph"
import NodeSquareProgram from "@/lib/sigma-square"
import NotePreviewPanel from "@/components/NotePreviewPanel"
import { NOTE_NODE_COLOR, noteNodeAttrs } from "@/lib/noteGraphUtils"
// Sidebar width is set inline (260px) in the flex layout

// ---------------------------------------------------------------------------
// Tag graph fetcher (S167) -- TagGraphData type moved to ./Viz/types
// ---------------------------------------------------------------------------

async function fetchTagGraph(): Promise<TagGraphData> {
  const res = await fetch(`${API_BASE}/tags/graph`)
  if (!res.ok) throw new Error("Failed to fetch tag graph")
  return res.json() as Promise<TagGraphData>
}

// ---------------------------------------------------------------------------
// Mastery / retention overlay fetcher -- types moved to ./Viz/types
// ---------------------------------------------------------------------------

async function fetchMasteryConcepts(docIds: string[]): Promise<MasteryConceptsResponse> {
  const params = docIds.map((id) => `document_ids=${encodeURIComponent(id)}`).join("&")
  const res = await fetch(`${API_BASE}/mastery/concepts?${params}`)
  if (!res.ok) return { document_ids: docIds, concepts: [] }
  return res.json() as Promise<MasteryConceptsResponse>
}

/** Map mastery score to a color for the retention overlay. */
function masteryColor(mastery: number): string {
  if (mastery >= 0.7) return "#22c55e"   // green-500: strong
  if (mastery >= 0.4) return "#84cc16"   // lime-500: good
  if (mastery >= 0.15) return "#f97316"  // orange-500: weak
  return "#ef4444"                        // red-500: critical
}

const BLIND_SPOT_COLOR = "#94a3b8" // slate-400: no flashcards

// Diagram-derived node types that use the hexagon renderer (S136)
const DIAGRAM_NODE_TYPES: ReadonlySet<string> = new Set(["COMPONENT", "ACTOR", "ENTITY_DM", "STEP"])

const TYPE_COLORS: Record<EntityType, string> = {
  PERSON: "#3b82f6",
  ORGANIZATION: "#8b5cf6",
  PLACE: "#10b981",
  CONCEPT: "#f59e0b",
  EVENT: "#ef4444",
  TECHNOLOGY: "#06b6d4",
  DATE: "#6b7280",
  // Tech-specific types (S135)
  LIBRARY: "#0ea5e9",
  DESIGN_PATTERN: "#d946ef",
  ALGORITHM: "#f97316",
  DATA_STRUCTURE: "#84cc16",
  PROTOCOL: "#a78bfa",
  API_ENDPOINT: "#fb7185",
  // Diagram-derived types (S136)
  COMPONENT: "#14b8a6",   // teal-500
  ACTOR: "#f43f5e",       // rose-500
  ENTITY_DM: "#a3e635",   // lime-400
  STEP: "#fbbf24",        // amber-400
}

const DEFAULT_COLOR = "#94a3b8"
const DIM_COLOR = "rgba(200,200,200,0.15)"

// Core graph + DocListItem types moved to ./Viz/types.

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchGraphData(
  documentId: string | null,
  scope: "document" | "all",
  viewMode: "knowledge_graph" | "call_graph",
  showCrossBook: boolean = false,
  includeNotes: boolean = false,
): Promise<GraphData> {
  const url =
    scope === "document" && documentId
      ? `${API_BASE}/graph/${documentId}?type=${viewMode}&include_notes=${includeNotes}`
      : `${API_BASE}/graph?doc_ids=&include_same_concept=${showCrossBook}&include_notes=${includeNotes}`
  const res = await fetch(url)
  if (!res.ok) throw new Error("Failed to fetch graph data")
  return res.json() as Promise<GraphData>
}

async function fetchLearningPath(
  documentId: string,
  startEntity: string,
): Promise<LearningPathData> {
  const url = `${API_BASE}/graph/learning-path?document_id=${encodeURIComponent(documentId)}&start_entity=${encodeURIComponent(startEntity)}`
  const res = await fetch(url)
  if (!res.ok) throw new Error("Failed to fetch learning path")
  return res.json() as Promise<LearningPathData>
}

async function fetchDocList(): Promise<DocListItem[]> {
  const res = await fetch(`${API_BASE}/documents?sort=newest&page=1&page_size=100`)
  if (!res.ok) return []
  const data = (await res.json()) as { items: DocListItem[] }
  return data.items ?? []
}

// ---------------------------------------------------------------------------
// Graph builder
// ---------------------------------------------------------------------------

// Purple color for PREREQUISITE_OF edges (S139)
const PREREQ_EDGE_COLOR = "#a855f7"  // purple-500

// SAME_CONCEPT edge colors (S141)
// Sigma.js does not natively support dashed/dotted edges without a custom edge program.
// We differentiate SAME_CONCEPT edges by color and low weight (0.5 vs 1.0 default).
const SAME_CONCEPT_COLOR = "#94a3b8"         // slate-400 -- no contradiction
const SAME_CONCEPT_CONTRADICTION_COLOR = "#ef4444"  // red-500 -- contradiction detected

// Note node edge colors (S172)
const WRITTEN_ABOUT_EDGE_COLOR = "#94a3b8"  // slate-400 -- thin grey lines
const LINKS_TO_EDGE_COLOR = "#6366f1"       // indigo-500 -- note-to-note
// NOTE_NODE_COLOR imported from noteGraphUtils

function buildGraph(nodes: GraphNode[], edges: GraphEdge[]): Graph {
  // Use mixed graph to support both undirected (CO_OCCURS) and directed (PREREQUISITE_OF) edges
  const g = new Graph({ type: "mixed" })
  // Only include non-note nodes in frequency scaling (note size is set by outgoing_link_count)
  const entityNodes = nodes.filter((n) => n.type !== "note")
  const frequencies = entityNodes.map((n) => n.size)
  const minFreq = Math.min(...frequencies, 1)
  const maxFreq = Math.max(...frequencies, 1)
  const scaleSize = (freq: number) =>
    maxFreq === minFreq ? 10 : 4 + ((freq - minFreq) / (maxFreq - minFreq)) * 16

  nodes.forEach((node) => {
    // Note nodes (S172): square renderer, indigo color, size from outgoing_link_count
    if (node.type === "note") {
      const linkCount = node.outgoing_link_count ?? 1
      const nid = node.note_id ?? node.id
      g.addNode(node.id, {
        ...noteNodeAttrs(node.label, nid, linkCount),
        frequency: linkCount,
        source_image_id: "",
        x: Math.random() * 200 - 100,
        y: Math.random() * 200 - 100,
      })
      return
    }
    const attrs: Record<string, unknown> = {
      label: node.label,
      entityType: node.type,
      frequency: node.size,
      source_image_id: node.source_image_id ?? "",
      x: Math.random() * 200 - 100,
      y: Math.random() * 200 - 100,
      size: scaleSize(node.size),
      color: TYPE_COLORS[node.type as EntityType] ?? DEFAULT_COLOR,
    }
    // COMPONENT nodes use the hexagon renderer (S136)
    if (node.type === "COMPONENT") {
      attrs.type = "hexagon"
    }
    g.addNode(node.id, attrs)
  })

  edges.forEach((edge, idx) => {
    if (g.hasNode(edge.source) && g.hasNode(edge.target) && edge.source !== edge.target) {
      if (!g.hasEdge(edge.source, edge.target)) {
        const isPrereq = edge.relation === "PREREQUISITE_OF"
        const isSameConcept = edge.relation === "SAME_CONCEPT"
        const isWrittenAbout =
          edge.relation === "WRITTEN_ABOUT" || edge.relation === "TAG_IS_CONCEPT"
        const isLinksTo = edge.relation === "LINKS_TO"

        if (isSameConcept) {
          // SAME_CONCEPT: undirected, low weight, gray or red based on contradiction (S141)
          const edgeColor = edge.contradiction
            ? SAME_CONCEPT_CONTRADICTION_COLOR
            : SAME_CONCEPT_COLOR
          g.addUndirectedEdge(edge.source, edge.target, {
            key: `e-${idx}`,
            weight: edge.weight ?? 0.5,
            color: edgeColor,
            relation: "SAME_CONCEPT",
            size: 0.5,
          })
          return
        }

        if (isWrittenAbout) {
          // Note -> Entity: thin grey undirected line (S172)
          g.addUndirectedEdge(edge.source, edge.target, {
            key: `e-${idx}`,
            weight: edge.weight ?? 0.5,
            color: WRITTEN_ABOUT_EDGE_COLOR,
            relation: edge.relation,
            size: 0.5,
          })
          return
        }

        if (isLinksTo) {
          // Note -> Note: indigo undirected line (S172)
          // Sigma does not natively support dashed edges; use distinct color.
          g.addUndirectedEdge(edge.source, edge.target, {
            key: `e-${idx}`,
            weight: edge.weight ?? 0.5,
            color: LINKS_TO_EDGE_COLOR,
            relation: "LINKS_TO",
            size: 0.5,
          })
          return
        }

        const edgeAttrs: Record<string, unknown> = {
          key: `e-${idx}`,
          weight: edge.weight ?? 1,
          color: isPrereq ? PREREQ_EDGE_COLOR : "#e2e8f0",
          relation: edge.relation ?? "CO_OCCURS",
        }
        if (isPrereq) {
          // Directed edge for PREREQUISITE_OF to show arrow direction
          g.addDirectedEdge(edge.source, edge.target, edgeAttrs)
        } else {
          g.addUndirectedEdge(edge.source, edge.target, edgeAttrs)
        }
      }
    }
  })

  if (g.order > 0) {
    forceAtlas2.assign(g, {
      iterations: 100,
      settings: forceAtlas2.inferSettings(g),
    })
  }

  return g
}

// ---------------------------------------------------------------------------
// Learning path graph builder (S117)
// Builds a directed Graphology graph from learning-path API data.
// ---------------------------------------------------------------------------

const LP_EDGE_COLOR = "#f97316" // orange-500

function buildLearningPathGraph(data: LearningPathData): Graph {
  // Use a directed graph so Sigma renders arrows
  const g = new Graph({ type: "directed" })

  const nodeById: Record<string, LearningPathNode> = {}
  data.nodes.forEach((n) => {
    nodeById[n.entity_id] = n
  })

  const maxDepth = data.nodes.reduce((max, n) => Math.max(max, n.depth), 0)

  data.nodes.forEach((node) => {
    if (!g.hasNode(node.entity_id)) {
      g.addNode(node.entity_id, {
        label: node.name,
        entityType: node.entity_type,
        frequency: 1,
        depth: node.depth,
        x: Math.random() * 200 - 100,
        // Spread nodes vertically by depth: deeper prerequisites lower on screen
        y: maxDepth > 0 ? ((maxDepth - node.depth) / maxDepth) * 200 - 100 : 0,
        size: 10,
        color: TYPE_COLORS[node.entity_type as EntityType] ?? DEFAULT_COLOR,
      })
    }
  })

  data.edges.forEach((edge, idx) => {
    // Look up IDs from name
    const fromNode = data.nodes.find((n) => n.name === edge.from_entity)
    const toNode = data.nodes.find((n) => n.name === edge.to_entity)
    if (!fromNode || !toNode) return
    const from = fromNode.entity_id
    const to = toNode.entity_id
    if (g.hasNode(from) && g.hasNode(to) && from !== to) {
      if (!g.hasEdge(from, to)) {
        g.addEdge(from, to, {
          key: `lp-e-${idx}`,
          weight: edge.confidence,
          color: LP_EDGE_COLOR,
          type: "PREREQUISITE_OF",
        })
      }
    }
  })

  if (g.order > 0) {
    forceAtlas2.assign(g, {
      iterations: 80,
      settings: forceAtlas2.inferSettings(g),
    })
  }

  return g
}

// ---------------------------------------------------------------------------
// Cluster graph builder (S181)
// Builds a Graphology graph where non-expanded entity types are collapsed into
// single cluster nodes.  Expanded types and note nodes render as individuals.
// ---------------------------------------------------------------------------

function buildClusterGraphology(
  nodes: GraphNode[],
  edges: GraphEdge[],
  clusterDefs: ClusterNodeDef[],
  expandedTypes: Set<string>,
): Graph {
  const g = new Graph({ type: "mixed" })

  // Map from individual node ID -> clusterId for non-expanded entity nodes
  const nodeToCluster = new Map<string, string>()
  for (const node of nodes) {
    if (node.type === "note") continue
    if (!expandedTypes.has(node.type)) {
      nodeToCluster.set(node.id, `cluster:${node.type}`)
    }
  }

  // Add cluster nodes
  const maxCount = Math.max(...clusterDefs.map((c) => c.count), 1)
  for (const cluster of clusterDefs) {
    g.addNode(cluster.clusterId, {
      label: cluster.label,
      entityType: "cluster",
      clusterEntityType: cluster.entityType,
      frequency: cluster.count,
      isCluster: true,
      source_image_id: "",
      x: Math.random() * 200 - 100,
      y: Math.random() * 200 - 100,
      size: 12 + (cluster.count / maxCount) * 28,
      color: TYPE_COLORS[cluster.entityType as EntityType] ?? DEFAULT_COLOR,
    })
  }

  // Add individual nodes for expanded types + note nodes
  const individualNodes = nodes.filter((n) => expandedTypes.has(n.type) || n.type === "note")
  const entityFreqs = individualNodes.filter((n) => n.type !== "note").map((n) => n.size)
  const minFreq = Math.min(...entityFreqs, 1)
  const maxFreq = Math.max(...entityFreqs, 1)
  const scaleSize = (freq: number) =>
    maxFreq === minFreq ? 10 : 4 + ((freq - minFreq) / (maxFreq - minFreq)) * 16

  for (const node of individualNodes) {
    if (node.type === "note") {
      const linkCount = node.outgoing_link_count ?? 1
      const nid = node.note_id ?? node.id
      g.addNode(node.id, {
        ...noteNodeAttrs(node.label, nid, linkCount),
        frequency: linkCount,
        source_image_id: "",
        isCluster: false,
        x: Math.random() * 200 - 100,
        y: Math.random() * 200 - 100,
      })
    } else {
      g.addNode(node.id, {
        label: node.label,
        entityType: node.type,
        frequency: node.size,
        source_image_id: node.source_image_id ?? "",
        isCluster: false,
        x: Math.random() * 200 - 100,
        y: Math.random() * 200 - 100,
        size: scaleSize(node.size),
        color: TYPE_COLORS[node.type as EntityType] ?? DEFAULT_COLOR,
      })
    }
  }

  // Add edges: map individual node IDs to cluster IDs where applicable
  for (const [idx, edge] of edges.entries()) {
    const srcId = nodeToCluster.get(edge.source) ?? edge.source
    const tgtId = nodeToCluster.get(edge.target) ?? edge.target
    if (!g.hasNode(srcId) || !g.hasNode(tgtId) || srcId === tgtId) continue
    if (!g.hasEdge(srcId, tgtId) && !g.hasEdge(tgtId, srcId)) {
      g.addUndirectedEdge(srcId, tgtId, {
        key: `ce-${idx}`,
        weight: edge.weight ?? 1,
        color: "#e2e8f0",
      })
    }
  }

  if (g.order > 0) {
    forceAtlas2.assign(g, { iterations: 80, settings: forceAtlas2.inferSettings(g) })
  }

  return g
}

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

        {/* ---- Header bar (matches Study/Notes pattern) ---- */}
        <div className="flex items-center justify-between border-b border-border bg-card/30 px-6 py-2.5 backdrop-blur-md shrink-0">
          <div className="flex items-center gap-6">
            <h1 className="text-xl font-bold tracking-tight text-foreground">Viz</h1>

            {/* View mode pills */}
            <div className="flex items-center gap-1 rounded-full border border-border bg-muted/30 p-0.5">
              {viewModes.map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  onClick={() => {
                    setViewMode(key)
                    void queryClient.invalidateQueries({ queryKey })
                  }}
                  className={`flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-medium transition-all ${
                    viewMode === key
                      ? "bg-primary text-primary-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                  }`}
                >
                  <Icon size={13} />
                  {label}
                </button>
              ))}
            </div>

            {/* Scope toggle -- hidden for Tags mode */}
            {viewMode !== "tags" && (
              <div className="flex items-center gap-1 rounded-full border border-border bg-muted/30 p-0.5">
                {(["document", "all"] as const).map((s) => (
                  <button
                    key={s}
                    onClick={() => {
                      setScope(s)
                      void queryClient.invalidateQueries({ queryKey })
                    }}
                    className={`rounded-full px-3 py-1.5 text-xs font-medium transition-all ${
                      scope === s
                        ? "bg-secondary text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {s === "document" ? "This doc" : "All docs"}
                  </button>
                ))}
              </div>
            )}
          </div> {/* End header left side (946) */}

          <div className="flex items-center gap-3"> {/* Header right side */}
            {graphStats && (
              <div className="flex items-center gap-2 rounded-full border border-border bg-card/50 px-3 py-1">
                <span className="text-[10px] font-semibold text-muted-foreground uppercase">
                  {graphStats.nodeCount} nodes
                </span>
                <span className="text-border">|</span>
                <span className="text-[10px] font-semibold text-muted-foreground uppercase">
                  {graphStats.edgeCount} edges
                </span>
              </div>
            )}
          </div>
        </div> {/* End header bar (945) */}

        {/* ---- Main content: sidebar + graph canvas ---- */}
        <div className="flex flex-1 overflow-hidden" style={{ minHeight: 0 }}>

          {/* ---- Sidebar panel ---- */}
          {viewMode !== "tags" && (
            <div
              className="flex flex-col border-r border-border bg-card/20 overflow-y-auto shrink-0 custom-scrollbar"
              style={{ width: 260 }}
            >
              {/* Browsing / Context Selection */}
              <div className="p-4 py-3 border-b border-border/50">
                <div className="flex items-center gap-2 mb-2.5">
                  <Library size={13} className="text-primary/70" />
                  <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Library</span>
                </div>
                
                {/* Search within Library/Entities */}
                <div className="relative mb-3">
                  <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground/40" />
                  <input
                    type="text"
                    value={docPickerSearch}
                    onChange={(e) => {
                      setDocPickerSearch(e.target.value)
                      // Only update global search if not specifically filtering the library list
                      if (!e.target.value) setSearch("")
                    }}
                    placeholder="Filter documents..."
                    className="w-full rounded-lg border border-border bg-background pl-8 pr-3 py-2 text-[11px] text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                  {docPickerSearch && (
                    <button
                      onClick={() => setDocPickerSearch("")}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      <X size={12} />
                    </button>
                  )}
                </div>

                {/* Quick select list or "All" toggle */}
                <div className="space-y-0.5 max-h-[220px] overflow-y-auto px-1 -mx-1 custom-scrollbar">
                  <button
                    onClick={() => handleDocSelect(null)}
                    className={`flex items-center gap-2 w-full text-left px-2 py-1.5 rounded-md text-[11px] transition-colors ${
                      !activeDocumentId ? "bg-primary/10 text-primary font-semibold" : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                    }`}
                  >
                    <BookOpen size={12} className={!activeDocumentId ? "text-primary" : "text-muted-foreground/50"} />
                    <span className="truncate">All documents</span>
                  </button>
                  
                  {filteredDocList.slice(0, 15).map((doc) => (
                    <button
                      key={doc.id}
                      onClick={() => handleDocSelect(doc.id)}
                      className={`flex items-center gap-2 w-full text-left px-2 py-1.5 rounded-md text-[11px] transition-colors ${
                        activeDocumentId === doc.id ? "bg-primary/10 text-primary font-semibold" : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                      }`}
                      title={doc.title}
                    >
                      <FileText size={12} className={activeDocumentId === doc.id ? "text-primary" : "text-muted-foreground/50"} />
                      <span className="truncate">{doc.title}</span>
                    </button>
                  ))}
                  
                  {filteredDocList.length > 15 && (
                    <p className="px-2 py-1 text-[9px] text-muted-foreground/50 italic">
                      + {filteredDocList.length - 15} more... search to filter
                    </p>
                  )}
                  
                  {filteredDocList.length === 0 && docPickerSearch && (
                    <p className="px-2 py-3 text-[10px] text-muted-foreground/50 text-center italic">
                      No matching documents
                    </p>
                  )}
                </div>
              </div>

              {/* Notes Context section (if notes layer is on) */}
              {showNotes && (
                <div className="p-4 py-3 border-b border-border/50 bg-yellow-50/10">
                  <div className="flex items-center gap-2 mb-2.5">
                    <StickyNote size={13} className="text-yellow-600/70" />
                    <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Notes in Context</span>
                  </div>
                  
                  <div className="space-y-0.5 max-h-[160px] overflow-y-auto px-1 -mx-1 custom-scrollbar">
                    {!filteredGraph || filteredGraph.nodes().filter(n => filteredGraph.getNodeAttribute(n, "type") === "note").length === 0 ? (
                      <p className="px-2 py-3 text-[10px] text-muted-foreground/50 text-center italic">
                        No notes found in graph
                      </p>
                    ) : (
                      filteredGraph.nodes()
                        .filter(n => filteredGraph.getNodeAttribute(n, "type") === "note")
                        .slice(0, 10)
                        .map((n) => {
                          const label = filteredGraph.getNodeAttribute(n, "label") as string
                          const nodeNoteId = filteredGraph.getNodeAttribute(n, "note_id") as string
                          return (
                            <button
                              key={n}
                              onClick={() => {
                                setSelectedNoteId(nodeNoteId)
                                setSelectedNode(null)
                                // Scroll to node is handled by useEffect on selectedNoteId
                              }}
                              className={`flex items-start gap-2 w-full text-left px-2 py-1.5 rounded-md text-[11px] transition-colors ${
                                selectedNoteId === nodeNoteId ? "bg-yellow-500/10 text-yellow-700 font-semibold" : "text-muted-foreground hover:bg-yellow-500/5 hover:text-foreground"
                              }`}
                            >
                              <StickyNote size={11} className="mt-0.5 shrink-0 opacity-50" />
                              <span className="line-clamp-2">{label}</span>
                            </button>
                          )
                        })
                    )}
                  </div>
                </div>
              )}

              {/* Learning path: start entity input (S117) */}
              {viewMode === "learning_path" && (
                <div className="p-4 border-b border-border/50">
                  <p className="mb-2 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">
                    Start Entity
                  </p>
                  <div className="flex gap-1.5">
                    <input
                      type="text"
                      value={lpInputDraft}
                      onChange={(e) => setLpInputDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") setLearningPathStart(lpInputDraft.trim())
                      }}
                      placeholder="Concept name..."
                      className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                    <button
                      onClick={() => setLearningPathStart(lpInputDraft.trim())}
                      className="rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                    >
                      Go
                    </button>
                  </div>
                  <p className="mt-1.5 text-[10px] text-muted-foreground/60">
                    Orange arrows show prerequisite chains
                  </p>
                </div>
              )}

              {/* Layers section */}
              <div className="p-4 border-b border-border/50">
                <div className="flex items-center gap-2 mb-3">
                  <Eye size={13} className="text-primary/70" />
                  <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Layers</span>
                </div>
                <div className="grid grid-cols-2 gap-1.5">
                  {[
                    { label: "Diagrams", checked: showDiagramNodes, toggle: () => setShowDiagramNodes((v) => !v), color: "#14b8a6" },
                    { label: "Prerequisites", checked: showPrerequisites, toggle: () => setShowPrerequisites((v) => !v), color: PREREQ_EDGE_COLOR },
                    { label: "Cross-book", checked: showCrossBook, toggle: () => setShowCrossBook((v) => !v), color: SAME_CONCEPT_COLOR },
                    { label: "Notes", checked: showNotes, toggle: () => setShowNotes((v) => !v), color: NOTE_NODE_COLOR },
                    { label: "Retention", checked: showRetention, toggle: () => setShowRetention((v) => !v), color: "#22c55e" },
                  ].map((layer) => (
                    <button
                      key={layer.label}
                      onClick={layer.toggle}
                      className={`flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs transition-all ${
                        layer.checked
                          ? "bg-accent/60 text-foreground border border-border"
                          : "text-muted-foreground/60 border border-transparent hover:bg-accent/30"
                      }`}
                    >
                      <span
                        className={`inline-block h-2 w-2 rounded-full shrink-0 transition-opacity ${layer.checked ? "opacity-100" : "opacity-30"}`}
                        style={{ backgroundColor: layer.color }}
                      />
                      <span className="truncate font-medium">{layer.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Needs Attention panel -- visible when retention overlay is active */}
              {showRetention && masteryData?.concepts && masteryData.concepts.filter((c) => c.no_flashcards || c.mastery < 0.3).length > 0 && (
                <div className="p-4 py-3 border-b border-border/50">
                  <div className="flex items-center gap-2 mb-2.5">
                    <AlertTriangle size={13} className="text-amber-500/70" />
                    <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Needs Attention</span>
                  </div>
                  <p className="text-[10px] text-muted-foreground/60 mb-2">
                    Concepts with weak retention or no flashcards
                  </p>
                  <div className="space-y-0.5 max-h-[200px] overflow-y-auto px-1 -mx-1 custom-scrollbar">
                    {masteryData.concepts
                      .filter((c) => c.no_flashcards || c.mastery < 0.3)
                      .slice(0, 15)
                      .map((c) => (
                        <button
                          key={c.concept}
                          onClick={() => setSearch(c.concept)}
                          className="flex items-center justify-between gap-2 w-full text-left px-2 py-1.5 rounded-md text-[11px] text-muted-foreground hover:bg-accent/50 hover:text-foreground transition-colors"
                        >
                          <span className="flex items-center gap-1.5 truncate min-w-0">
                            <span
                              className="inline-block h-2 w-2 rounded-full shrink-0"
                              style={{ backgroundColor: c.no_flashcards ? BLIND_SPOT_COLOR : masteryColor(c.mastery) }}
                            />
                            <span className="truncate">{c.concept}</span>
                          </span>
                          <span className={`text-[10px] font-mono shrink-0 ${
                            c.no_flashcards
                              ? "text-muted-foreground/40"
                              : c.mastery < 0.15
                                ? "text-red-500"
                                : "text-amber-500"
                          }`}>
                            {c.no_flashcards ? "blind spot" : `${Math.round(c.mastery * 100)}%`}
                          </span>
                        </button>
                      ))}
                  </div>
                </div>
              )}

              {/* Entity type filter */}
              <div className="p-4 flex-1">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <Filter size={13} className="text-primary/70" />
                    <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Entity Types</span>
                  </div>
                  <div className="flex gap-1">
                    <button
                      onClick={selectAllEntityTypes}
                      className="rounded px-1.5 py-0.5 text-[10px] font-semibold text-primary hover:bg-primary/10 transition-colors"
                    >
                      All
                    </button>
                    <span className="text-border">|</span>
                    <button
                      onClick={deselectAllEntityTypes}
                      className="rounded px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground hover:bg-accent transition-colors"
                    >
                      None
                    </button>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {ALL_ENTITY_TYPES.map((type) => (
                    <button
                      key={type}
                      onClick={() => toggleEntityType(type)}
                      className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition-all ${
                        activeTypes.has(type)
                          ? "bg-foreground/10 text-foreground border border-border shadow-sm"
                          : "text-muted-foreground/40 border border-transparent hover:text-muted-foreground hover:bg-accent/30"
                      }`}
                    >
                      <span
                        className={`inline-block h-2 w-2 rounded-full shrink-0 transition-opacity ${activeTypes.has(type) ? "opacity-100" : "opacity-25"}`}
                        style={{ backgroundColor: TYPE_COLORS[type] }}
                      />
                      {type.toLowerCase().replace(/_/g, " ")}
                    </button>
                  ))}
                </div>

                {/* Cluster view toggle */}
                <div className="mt-4 pt-3 border-t border-border/50">
                  <button
                    onClick={() => setClusterViewEnabled((v) => !v)}
                    className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs w-full transition-all ${
                      clusterViewEnabled
                        ? "bg-primary/10 text-primary border border-primary/30"
                        : "text-muted-foreground border border-transparent hover:bg-accent/30"
                    }`}
                  >
                    <Network size={13} />
                    <span className="font-medium">Cluster view</span>
                    <span className="ml-auto text-[10px] text-muted-foreground">
                      &gt;200 nodes
                    </span>
                  </button>
                </div>
              </div>
            </div>
          )}

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

            {/* Learning path states (S117) */}
            {lpNoInput && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-center p-6">
                <div className="rounded-2xl bg-muted/30 p-6">
                  <Zap size={48} className="text-muted-foreground/30" />
                </div>
                <p className="text-lg font-semibold text-foreground">Enter a start entity</p>
                <p className="text-sm text-muted-foreground max-w-xs">
                  Type a concept name in the sidebar and press Enter to view its prerequisite chain.
                </p>
              </div>
            )}

            {lpShowLoading && (
              <div className="absolute inset-0 flex flex-col gap-4 p-6">
                <Skeleton className="h-8 w-48" />
                <Skeleton className="flex-1 w-full rounded-lg" />
              </div>
            )}

            {lpShowError && (
              <div className="absolute inset-0 flex items-center justify-center p-6">
                <div className="flex flex-col items-center gap-3 rounded-2xl border border-red-200 bg-red-50 px-8 py-6 text-sm text-red-700">
                  <p className="font-semibold">Failed to load learning path</p>
                  <button
                    onClick={() => void lpRefetch()}
                    className="rounded-lg border border-red-300 bg-white px-4 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 transition-colors"
                  >
                    Retry
                  </button>
                </div>
              </div>
            )}

            {lpShowEmpty && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-center p-6">
                <div className="rounded-2xl bg-muted/30 p-6">
                  <Network size={48} className="text-muted-foreground/30" />
                </div>
                <p className="text-lg font-semibold text-foreground">
                  No prerequisite path found for &ldquo;{learningPathStart}&rdquo;
                </p>
                <p className="text-sm text-muted-foreground max-w-xs">
                  This entity has no PREREQUISITE_OF edges in this document. Try a different concept.
                </p>
              </div>
            )}

            {!noDocSelected && isLoading && viewMode !== "tags" && (
              <div className="absolute inset-0 flex flex-col gap-4 p-6">
                <Skeleton className="h-8 w-48" />
                <Skeleton className="flex-1 w-full rounded-lg" />
              </div>
            )}

            {!noDocSelected && !isLoading && isError && viewMode !== "tags" && (
              <div className="absolute inset-0 flex items-center justify-center p-6">
                <div className="flex flex-col items-center gap-3 rounded-2xl border border-red-200 bg-red-50 px-8 py-6 text-sm text-red-700">
                  <p className="font-semibold">Failed to load knowledge graph</p>
                  <button
                    onClick={() => void refetch()}
                    className="rounded-lg border border-red-300 bg-white px-4 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 transition-colors"
                  >
                    Retry
                  </button>
                </div>
              </div>
            )}

            {showEmpty && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-center p-6">
                <div className="rounded-2xl bg-muted/30 p-6">
                  <Network size={48} className="text-muted-foreground/30" />
                </div>
                <p className="text-lg font-semibold text-foreground">No knowledge graph yet</p>
                <p className="text-sm text-muted-foreground max-w-xs">
                  Ingest a document first -- entities and relationships will appear here.
                </p>
              </div>
            )}

            {showAllHidden && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-center p-6">
                <div className="rounded-2xl bg-muted/30 p-6">
                  <Filter size={48} className="text-muted-foreground/30" />
                </div>
                <p className="text-lg font-semibold text-foreground">
                  All entity types are hidden
                </p>
                <p className="text-sm text-muted-foreground max-w-xs">
                  {entityNodeCount} {entityNodeCount === 1 ? "entity" : "entities"} found.
                  Enable at least one entity type in the sidebar.
                </p>
              </div>
            )}

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
            {(filteredGraph && filteredGraph.order > 0) || viewMode === "tags" ? (
              <div className="absolute bottom-4 right-4 flex flex-col gap-1 z-10">
                <button
                  onClick={zoomIn}
                  className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background/90 text-foreground shadow-sm hover:bg-accent transition-all backdrop-blur-sm"
                  title="Zoom in"
                >
                  <Plus size={14} />
                </button>
                <button
                  onClick={zoomOut}
                  className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background/90 text-foreground shadow-sm hover:bg-accent transition-all backdrop-blur-sm"
                  title="Zoom out"
                >
                  <Minus size={14} />
                </button>
                <div className="h-px bg-border/50 mx-1" />
                <button
                  onClick={resetCamera}
                  className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background/90 text-foreground shadow-sm hover:bg-accent transition-all backdrop-blur-sm"
                  title="Fit to screen"
                >
                  <Maximize2 size={14} />
                </button>
              </div>
            ) : null}

            {/* Graph legend (bottom-left) -- switches between entity types and retention */}
            {showRetention && filteredGraph && filteredGraph.order > 0 ? (
              <div className="absolute bottom-4 left-4 z-10 rounded-xl border border-border bg-background/90 backdrop-blur-sm shadow-sm px-3 py-2.5 max-w-[240px]">
                <p className="text-[9px] font-bold text-muted-foreground/60 uppercase tracking-widest mb-2">Retention Strength</p>
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {([
                    ["#ef4444", "Critical (<15%)"],
                    ["#f97316", "Weak (15-40%)"],
                    ["#84cc16", "Good (40-70%)"],
                    ["#22c55e", "Strong (>70%)"],
                    [BLIND_SPOT_COLOR, "No flashcards"],
                  ] as const).map(([color, label]) => (
                    <div key={label} className="flex items-center gap-1">
                      <span
                        className="inline-block h-1.5 w-1.5 rounded-full"
                        style={{ backgroundColor: color }}
                      />
                      <span className="text-[10px] text-muted-foreground">{label}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : graphStats && graphStats.typeCounts.size > 0 ? (
              <div className="absolute bottom-4 left-4 z-10 rounded-xl border border-border bg-background/90 backdrop-blur-sm shadow-sm px-3 py-2.5 max-w-[200px]">
                <p className="text-[9px] font-bold text-muted-foreground/60 uppercase tracking-widest mb-2">Legend</p>
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {Array.from(graphStats.typeCounts.entries())
                    .filter(([t]) => t !== "cluster" && t !== "note")
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 8)
                    .map(([type, count]) => (
                      <div key={type} className="flex items-center gap-1">
                        <span
                          className="inline-block h-1.5 w-1.5 rounded-full"
                          style={{ backgroundColor: TYPE_COLORS[type as EntityType] ?? DEFAULT_COLOR }}
                        />
                        <span className="text-[10px] text-muted-foreground">
                          {type.toLowerCase().replace(/_/g, " ")} ({count})
                        </span>
                      </div>
                    ))}
                </div>
              </div>
            ) : null}

            {/* Note node preview panel (S172) */}
            {selectedNoteId && (
              <NotePreviewPanel
                noteId={selectedNoteId}
                onClose={() => setSelectedNoteId(null)}
              />
            )}

            {/* Node click popover */}
            {selectedNode && (
              <div
                className="fixed z-50 rounded-2xl border border-border bg-background/95 backdrop-blur-sm shadow-xl p-4 min-w-[200px] max-w-[280px]"
                style={{ left: selectedNode.screenX + 12, top: selectedNode.screenY - 70 }}
              >
                <button
                  onClick={() => setSelectedNode(null)}
                  className="absolute top-2 right-2 rounded p-0.5 text-muted-foreground/40 hover:text-foreground transition-colors"
                >
                  <X size={12} />
                </button>
                <div className="flex items-center gap-2 mb-2">
                  <span
                    className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
                    style={{
                      backgroundColor: TYPE_COLORS[selectedNode.type as EntityType] ?? DEFAULT_COLOR,
                    }}
                  />
                  <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wide">
                    {selectedNode.type.replace(/_/g, " ")}
                  </span>
                </div>
                <p className="text-sm font-bold text-foreground mb-1">
                  {selectedNode.label}
                </p>
                {viewMode === "learning_path" && lpBreadcrumb.length > 1 ? (
                  <div className="mb-3">
                    <p className="text-[10px] font-semibold text-muted-foreground mb-1 uppercase">Prerequisites</p>
                    <p className="text-xs text-foreground leading-relaxed">
                      {lpBreadcrumb.join(" -> ")}
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground mb-3">
                    {selectedNode.frequency} {selectedNode.frequency === 1 ? "mention" : "mentions"}
                  </p>
                )}
                {/* Image thumbnail for diagram-derived nodes (S136) */}
                {selectedNode.source_image_id && (
                  <div className="mb-3">
                    <img
                      src={`${API_BASE}/images/${selectedNode.source_image_id}/raw`}
                      alt="Source diagram"
                      className="w-full rounded-lg border border-border object-contain max-h-40"
                      onError={(e) => {
                        ;(e.target as HTMLImageElement).style.display = "none"
                      }}
                    />
                  </div>
                )}
                <button
                  onClick={() => {
                    const docId = activeDocumentId
                    const entityLabel = selectedNode.label
                    setSelectedNode(null)
                    if (docId) {
                      navigate(`/?doc=${encodeURIComponent(docId)}&search=${encodeURIComponent(entityLabel)}`)
                    } else {
                      navigate(`/?search=${encodeURIComponent(entityLabel)}`)
                    }
                  }}
                  className="w-full rounded-lg bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/20 transition-colors text-center"
                >
                  Find in document
                </button>
              </div>
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
