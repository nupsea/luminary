import { useQuery, useQueryClient } from "@tanstack/react-query"
import Graph from "graphology"
import forceAtlas2 from "graphology-layout-forceatlas2"
import { Maximize2, Minus, Network, Plus } from "lucide-react"
import { Component, useEffect, useMemo, useRef, useState } from "react"
import type { ErrorInfo, ReactNode } from "react"
import Sigma from "sigma"
import type { SigmaEdgeEventPayload, SigmaNodeEventPayload } from "sigma/types"
import { useNavigate } from "react-router-dom"
import { Skeleton } from "@/components/ui/skeleton"
import NodeHexagonProgram from "@/lib/sigma-hexagon"
import { logger } from "@/lib/logger"
import { useAppStore } from "../store"

// ---------------------------------------------------------------------------
// Learning path types (S117)
// ---------------------------------------------------------------------------

interface LearningPathNode {
  entity_id: string
  name: string
  entity_type: string
  depth: number
}

interface LearningPathEdge {
  from_entity: string
  to_entity: string
  confidence: number
}

interface LearningPathData {
  start_entity: string
  document_id: string
  nodes: LearningPathNode[]
  edges: LearningPathEdge[]
}

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

const API_BASE = "http://localhost:8000"
const SIDEBAR_W = 240

const ALL_ENTITY_TYPES = [
  "PERSON",
  "ORGANIZATION",
  "PLACE",
  "CONCEPT",
  "EVENT",
  "TECHNOLOGY",
  "DATE",
  // Tech-specific types (S135)
  "LIBRARY",
  "DESIGN_PATTERN",
  "ALGORITHM",
  "DATA_STRUCTURE",
  "PROTOCOL",
  "API_ENDPOINT",
  // Diagram-derived types (S136) -- rendered as hexagons for COMPONENT
  "COMPONENT",
  "ACTOR",
  "ENTITY_DM",
  "STEP",
] as const

type EntityType = (typeof ALL_ENTITY_TYPES)[number]

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

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GraphNode {
  id: string
  label: string
  type: string
  size: number
  source_image_id?: string  // set for diagram-derived nodes (S136)
}

interface GraphEdge {
  source: string
  target: string
  weight: number
  relation?: string  // e.g. "PREREQUISITE_OF", "CO_OCCURS", "IMPLEMENTS", "SAME_CONCEPT"
  contradiction?: boolean  // true when SAME_CONCEPT edge has detected contradiction (S141)
}

interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

interface SelectedNodeInfo {
  id: string
  label: string
  type: string
  frequency: number
  screenX: number
  screenY: number
  source_image_id?: string  // set for diagram-derived nodes (S136)
}

interface DocListItem {
  id: string
  title: string
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchGraphData(
  documentId: string | null,
  scope: "document" | "all",
  viewMode: "knowledge_graph" | "call_graph",
  showCrossBook: boolean = false,
): Promise<GraphData> {
  const url =
    scope === "document" && documentId
      ? `${API_BASE}/graph/${documentId}?type=${viewMode}`
      : `${API_BASE}/graph?doc_ids=&include_same_concept=${showCrossBook}`
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

function buildGraph(nodes: GraphNode[], edges: GraphEdge[]): Graph {
  // Use mixed graph to support both undirected (CO_OCCURS) and directed (PREREQUISITE_OF) edges
  const g = new Graph({ type: "mixed" })
  const frequencies = nodes.map((n) => n.size)
  const minFreq = Math.min(...frequencies, 1)
  const maxFreq = Math.max(...frequencies, 1)
  const scaleSize = (freq: number) =>
    maxFreq === minFreq ? 10 : 4 + ((freq - minFreq) / (maxFreq - minFreq)) * 16

  nodes.forEach((node) => {
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

        if (isSameConcept) {
          // SAME_CONCEPT: undirected, low weight, gray or red based on contradiction (S141)
          // Sigma does not natively support dashed edges; use low weight + distinct color.
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
// Main page
// ---------------------------------------------------------------------------

export default function Viz() {
  const activeDocumentId = useAppStore((s) => s.activeDocumentId)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const mountTime = useRef(Date.now())

  // Raw sigma instance — NOT stored in React state to avoid re-render loops
  const sigmaRef = useRef<Sigma | null>(null)
  // The div that sigma renders into
  const canvasRef = useRef<HTMLDivElement>(null)

  const [activeTypes, setActiveTypes] = useState<Set<EntityType>>(new Set(ALL_ENTITY_TYPES))
  const [search, setSearch] = useState("")
  const [scope, setScope] = useState<"document" | "all">("document")
  const [viewMode, setViewMode] = useState<"knowledge_graph" | "call_graph" | "learning_path">("knowledge_graph")
  const [selectedNode, setSelectedNode] = useState<SelectedNodeInfo | null>(null)
  const [edgeTooltip, setEdgeTooltip] = useState<string | null>(null)
  // Diagrams layer toggle: show/hide diagram-derived nodes (S136)
  const [showDiagramNodes, setShowDiagramNodes] = useState(true)
  // Prerequisites layer toggle: show/hide PREREQUISITE_OF edges (S139)
  const [showPrerequisites, setShowPrerequisites] = useState(true)
  // Cross-book layer toggle: show/hide SAME_CONCEPT edges (S141) -- default off (noisy)
  const [showCrossBook, setShowCrossBook] = useState(false)
  // Learning path state (S117)
  const [learningPathStart, setLearningPathStart] = useState("")
  const [lpInputDraft, setLpInputDraft] = useState("")

  // Document list for the picker
  const { data: docList } = useQuery({
    queryKey: ["viz-doc-list"],
    queryFn: fetchDocList,
    staleTime: 30_000,
  })

  const noDocSelected = scope === "document" && !activeDocumentId

  const queryKey = ["graph", scope, activeDocumentId, viewMode, showCrossBook]
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey,
    queryFn: () => fetchGraphData(activeDocumentId, scope, viewMode as "knowledge_graph" | "call_graph", showCrossBook),
    staleTime: 30_000,
    enabled: !noDocSelected && viewMode !== "learning_path",
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

  useEffect(() => {
    if (!isLoading && data) {
      logger.info("[Viz] loaded", {
        duration_ms: Date.now() - mountTime.current,
        nodes: data.nodes.length,
      })
    }
  }, [isLoading, data])

  // Build filtered graphology graph from API data + active entity types (or learning path)
  const filteredGraph = useMemo(() => {
    if (viewMode === "learning_path") {
      if (!lpData || lpData.nodes.length === 0) return null
      return buildLearningPathGraph(lpData)
    }
    if (!data) return null
    const visibleNodes = data.nodes.filter((n) => {
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
    return buildGraph(visibleNodes, visibleEdges)
  }, [data, activeTypes, viewMode, lpData, showDiagramNodes, showPrerequisites, showCrossBook])

  // ---------------------------------------------------------------------------
  // Core effect: mount/update raw Sigma instance when filteredGraph changes
  // ---------------------------------------------------------------------------
  useEffect(() => {
    // Destroy previous instance first
    if (sigmaRef.current) {
      sigmaRef.current.kill()
      sigmaRef.current = null
    }

    const el = canvasRef.current
    if (!el || !filteredGraph || filteredGraph.order === 0) return

    const s = new Sigma(filteredGraph, el, {
      renderEdgeLabels: false,
      defaultEdgeColor: viewMode === "learning_path" ? LP_EDGE_COLOR : "#e2e8f0",
      labelSize: 12,
      labelWeight: "normal",
      // Register hexagon node program for COMPONENT nodes (S136).
      // Nodes without a type attribute use sigma's default renderer (NodePointProgram).
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- sigma generic variance
      nodeProgramClasses: {
        hexagon: NodeHexagonProgram as any,
      },
    })

    // Node click → popover
    s.on("clickNode", (payload: SigmaNodeEventPayload) => {
      const { node, event } = payload
      const pos = s.graphToViewport({
        x: filteredGraph.getNodeAttribute(node, "x") as number,
        y: filteredGraph.getNodeAttribute(node, "y") as number,
      })
      const rect = el.getBoundingClientRect()
      setSelectedNode({
        id: node,
        label: filteredGraph.getNodeAttribute(node, "label") as string,
        type: filteredGraph.getNodeAttribute(node, "entityType") as string,
        frequency: filteredGraph.getNodeAttribute(node, "frequency") as number,
        screenX: rect.left + pos.x,
        screenY: rect.top + pos.y,
        source_image_id: (filteredGraph.getNodeAttribute(node, "source_image_id") as string | undefined) ?? "",
      })
      event.preventSigmaDefault()
    })

    // Edge hover → tooltip
    s.on("enterEdge", (payload: SigmaEdgeEventPayload) => {
      const edgeType =
        (filteredGraph.getEdgeAttribute(payload.edge, "type") as string | undefined) ?? "CO_OCCURS"
      setEdgeTooltip(edgeType)
    })
    s.on("leaveEdge", () => setEdgeTooltip(null))

    // Click blank area → deselect node
    s.on("clickStage", () => setSelectedNode(null))

    sigmaRef.current = s

    return () => {
      s.kill()
      sigmaRef.current = null
    }
  }, [filteredGraph])

  // ---------------------------------------------------------------------------
  // Search effect: update sigma reducers without rebuilding the instance
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const s = sigmaRef.current
    if (!s) return

    if (!search) {
      s.setSetting("nodeReducer", null)
      s.setSetting("edgeReducer", null)
      return
    }

    const q = search.toLowerCase()
    s.setSetting("nodeReducer", (_node: string, d: Record<string, unknown>) => {
      const label = (d.label as string) ?? ""
      if (label.toLowerCase().includes(q)) return d
      return { ...d, color: DIM_COLOR, label: "" }
    })
    s.setSetting("edgeReducer", (_edge: string, d: Record<string, unknown>) => ({
      ...d,
      color: DIM_COLOR,
    }))

    // Pan to first matching node
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
  }, [search, filteredGraph]) // re-apply after sigma rebuilds

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

  const toggleType = (type: EntityType) => {
    setActiveTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------
  const showEmpty =
    !noDocSelected && !isLoading && !isError && (!data || data.nodes.length === 0) && viewMode !== "learning_path"
  const showAllHidden =
    filteredGraph !== null && filteredGraph.order === 0 && !!data && data.nodes.length > 0 && viewMode !== "learning_path"

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

  return (
    <VizErrorBoundary>
      {/*
        Absolute layout so heights are always definite:
          - outer div: position relative, fills 100% of <main> height
          - sidebar: absolute left column (SIDEBAR_W px wide)
          - graph area: absolute, fills the rest
        This avoids flex cross-axis height propagation issues entirely.
      */}
      <div style={{ position: "relative", width: "100%", height: "100vh", overflow: "hidden" }}>

        {/* ---- Controls sidebar ---- */}
        <div
          className="flex flex-col gap-4 border-r border-border bg-background p-4 overflow-y-auto"
          style={{ position: "absolute", left: 0, top: 0, width: SIDEBAR_W, bottom: 0 }}
        >
          {/* Document picker */}
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Document
            </p>
            <select
              value={activeDocumentId ?? ""}
              onChange={(e) => setActiveDocument(e.target.value || null)}
              className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            >
              <option value="">Select a document…</option>
              {(docList ?? []).map((doc) => (
                <option key={doc.id} value={doc.id}>{doc.title}</option>
              ))}
            </select>
          </div>

          {/* View toggle */}
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              View
            </p>
            <div className="flex flex-col rounded-md border border-border overflow-hidden text-xs">
              {(["knowledge_graph", "call_graph", "learning_path"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => {
                    setViewMode(v)
                    void queryClient.invalidateQueries({ queryKey })
                  }}
                  className={`flex-1 py-1.5 transition-colors ${
                    viewMode === v
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent"
                  }`}
                >
                  {v === "knowledge_graph" ? "Knowledge" : v === "call_graph" ? "Call Graph" : "Learning Path"}
                </button>
              ))}
            </div>
            {viewMode === "call_graph" && (
              <p className="mt-1 text-xs text-muted-foreground">Code documents only</p>
            )}
            {viewMode === "learning_path" && (
              <p className="mt-1 text-xs text-muted-foreground">Orange arrows = PREREQUISITE_OF</p>
            )}
          </div>

          {/* Learning path: start entity input (S117) */}
          {viewMode === "learning_path" && (
            <div>
              <p className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                Start entity
              </p>
              <input
                type="text"
                value={lpInputDraft}
                onChange={(e) => setLpInputDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") setLearningPathStart(lpInputDraft.trim())
                }}
                placeholder="Type a concept name..."
                className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <button
                onClick={() => setLearningPathStart(lpInputDraft.trim())}
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1 text-xs text-muted-foreground hover:bg-accent transition-colors"
              >
                Load path
              </button>
            </div>
          )}

          {/* Scope toggle */}
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Scope
            </p>
            <div className="flex rounded-md border border-border overflow-hidden text-xs">
              {(["document", "all"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => {
                    setScope(s)
                    void queryClient.invalidateQueries({ queryKey })
                  }}
                  className={`flex-1 py-1.5 capitalize transition-colors ${
                    scope === s
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent"
                  }`}
                >
                  {s === "document" ? "This doc" : "All docs"}
                </button>
              ))}
            </div>
          </div>

          {/* Search */}
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Search
            </p>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Find entity..."
              className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          {/* Layer toggles (S136, S139) */}
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Layers
            </p>
            <div className="space-y-1.5">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={showDiagramNodes}
                  onChange={() => setShowDiagramNodes((v) => !v)}
                  className="accent-primary"
                />
                <span className="text-xs text-foreground">Diagrams</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={showPrerequisites}
                  onChange={() => setShowPrerequisites((v) => !v)}
                  className="accent-primary"
                />
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: PREREQ_EDGE_COLOR }}
                />
                <span className="text-xs text-foreground">Prerequisites</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={showCrossBook}
                  onChange={() => setShowCrossBook((v) => !v)}
                  className="accent-primary"
                />
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: SAME_CONCEPT_COLOR }}
                />
                <span className="text-xs text-foreground">Cross-book</span>
              </label>
            </div>
          </div>

          {/* Entity type filter */}
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Entity types
            </p>
            <div className="space-y-1.5">
              {ALL_ENTITY_TYPES.map((type) => (
                <label key={type} className="flex items-center gap-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={activeTypes.has(type)}
                    onChange={() => toggleType(type)}
                    className="accent-primary"
                  />
                  <span
                    className="inline-block h-2.5 w-2.5 rounded-full flex-shrink-0"
                    style={{ backgroundColor: TYPE_COLORS[type] }}
                  />
                  <span className="text-xs text-foreground capitalize">{type.toLowerCase()}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        {/* ---- Graph area ---- */}
        <div
          style={{ position: "absolute", left: SIDEBAR_W, top: 0, right: 0, bottom: 0 }}
        >
          {/* State overlays — all use absolute fill so they sit in the same space */}

          {noDocSelected && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center p-6">
              <Network size={40} className="text-muted-foreground/40" />
              <p className="text-base font-semibold text-foreground">No document selected</p>
              <p className="text-sm text-muted-foreground max-w-xs">
                Choose a document from the dropdown on the left to explore its knowledge graph.
              </p>
            </div>
          )}

          {/* Learning path states (S117) */}
          {lpNoInput && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center p-6">
              <Network size={40} className="text-muted-foreground/40" />
              <p className="text-base font-semibold text-foreground">Enter a start entity</p>
              <p className="text-sm text-muted-foreground max-w-xs">
                Type a concept name in the "Start entity" input and press Enter to view its prerequisite chain.
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
              <div className="flex flex-col items-center gap-3 rounded-md border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700">
                <p className="font-medium">Failed to load learning path</p>
                <button
                  onClick={() => void lpRefetch()}
                  className="rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs text-red-700 hover:bg-red-50 transition-colors"
                >
                  Retry
                </button>
              </div>
            </div>
          )}

          {lpShowEmpty && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center p-6">
              <Network size={40} className="text-muted-foreground/40" />
              <p className="text-base font-semibold text-foreground">
                No prerequisite path found for "{learningPathStart}"
              </p>
              <p className="text-sm text-muted-foreground max-w-xs">
                This entity has no PREREQUISITE_OF edges in this document. Try a different concept.
              </p>
            </div>
          )}

          {!noDocSelected && isLoading && (
            <div className="absolute inset-0 flex flex-col gap-4 p-6">
              <Skeleton className="h-8 w-48" />
              <Skeleton className="flex-1 w-full rounded-lg" />
            </div>
          )}

          {!noDocSelected && !isLoading && isError && (
            <div className="absolute inset-0 flex items-center justify-center p-6">
              <div className="flex flex-col items-center gap-3 rounded-md border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700">
                <p className="font-medium">Failed to load knowledge graph</p>
                <button
                  onClick={() => void refetch()}
                  className="rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs text-red-700 hover:bg-red-50 transition-colors"
                >
                  Retry
                </button>
              </div>
            </div>
          )}

          {showEmpty && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center p-6">
              <Network size={40} className="text-muted-foreground/40" />
              <p className="text-base font-semibold text-foreground">No knowledge graph yet</p>
              <p className="text-sm text-muted-foreground max-w-xs">
                Ingest a document first — entities and relationships will appear here.
              </p>
            </div>
          )}

          {showAllHidden && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center p-6">
              <Network size={40} className="text-muted-foreground/40" />
              <p className="text-base font-semibold text-foreground">All entity types hidden</p>
              <p className="text-sm text-muted-foreground max-w-xs">
                {data!.nodes.length} {data!.nodes.length === 1 ? "entity" : "entities"} found —
                enable at least one entity type in the filter to see the graph.
              </p>
            </div>
          )}

          {/* The actual sigma canvas div — always rendered so canvasRef is always populated.
              Sigma mounts into this div via useEffect above. */}
          <div
            ref={canvasRef}
            style={{ width: "100%", height: "100%" }}
          />

          {/* Camera controls */}
          {filteredGraph && filteredGraph.order > 0 && (
            <div className="absolute bottom-4 right-4 flex flex-col gap-1 z-10">
              <button
                onClick={zoomIn}
                className="flex h-8 w-8 items-center justify-center rounded border border-border bg-background text-foreground shadow-sm hover:bg-accent"
                title="Zoom in"
              >
                <Plus size={14} />
              </button>
              <button
                onClick={zoomOut}
                className="flex h-8 w-8 items-center justify-center rounded border border-border bg-background text-foreground shadow-sm hover:bg-accent"
                title="Zoom out"
              >
                <Minus size={14} />
              </button>
              <button
                onClick={resetCamera}
                className="flex h-8 w-8 items-center justify-center rounded border border-border bg-background text-foreground shadow-sm hover:bg-accent"
                title="Fit to screen"
              >
                <Maximize2 size={14} />
              </button>
            </div>
          )}

          {/* Node click popover */}
          {selectedNode && (
            <div
              className="fixed z-50 rounded-lg border border-border bg-background shadow-lg p-3 min-w-[180px] max-w-[260px]"
              style={{ left: selectedNode.screenX + 8, top: selectedNode.screenY - 60 }}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <span
                  className="inline-block h-2 w-2 rounded-full flex-shrink-0"
                  style={{
                    backgroundColor: TYPE_COLORS[selectedNode.type as EntityType] ?? DEFAULT_COLOR,
                  }}
                />
                <span className="text-xs text-muted-foreground font-medium">{selectedNode.type}</span>
              </div>
              <p className="text-sm font-semibold text-foreground capitalize mb-1">
                {selectedNode.label}
              </p>
              {viewMode === "learning_path" && lpBreadcrumb.length > 1 ? (
                <div className="mb-2">
                  <p className="text-xs text-muted-foreground font-medium mb-1">Prerequisites:</p>
                  <p className="text-xs text-foreground">
                    {lpBreadcrumb.join(" -> ")}
                  </p>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground mb-2">
                  Mentions: {selectedNode.frequency}
                </p>
              )}
              {/* Image thumbnail for diagram-derived nodes (S136) */}
              {selectedNode.source_image_id && (
                <div className="mb-2">
                  <img
                    src={`${API_BASE}/images/${selectedNode.source_image_id}/raw`}
                    alt="Source diagram"
                    className="w-full rounded border border-border object-contain max-h-40"
                    onError={(e) => {
                      ;(e.target as HTMLImageElement).style.display = "none"
                    }}
                  />
                </div>
              )}
              <button
                onClick={() => {
                  setSelectedNode(null)
                  setActiveDocument(null)
                  navigate("/")
                }}
                className="text-xs text-primary underline hover:no-underline"
              >
                Find in document
              </button>
            </div>
          )}

          {/* Edge hover tooltip */}
          {edgeTooltip && (
            <div className="absolute bottom-16 right-4 rounded bg-foreground px-2 py-1 text-xs text-background z-10">
              {edgeTooltip}
            </div>
          )}
        </div>
      </div>
    </VizErrorBoundary>
  )
}
