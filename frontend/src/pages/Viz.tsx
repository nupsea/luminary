import {
  SigmaContainer,
  useCamera,
  useRegisterEvents,
  useSetSettings,
  useSigma,
} from "@react-sigma/core"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import Graph from "graphology"
import forceAtlas2 from "graphology-layout-forceatlas2"
import { Maximize2, Minus, Network, Plus } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import type { SigmaEdgeEventPayload, SigmaNodeEventPayload } from "sigma/types"
import { Skeleton } from "@/components/ui/skeleton"
import { logger } from "@/lib/logger"
import { useAppStore } from "../store"

const API_BASE = "http://localhost:8000"

const ALL_ENTITY_TYPES = [
  "PERSON",
  "ORGANIZATION",
  "PLACE",
  "CONCEPT",
  "EVENT",
  "TECHNOLOGY",
  "DATE",
] as const

type EntityType = (typeof ALL_ENTITY_TYPES)[number]

const TYPE_COLORS: Record<EntityType, string> = {
  PERSON: "#3b82f6",
  ORGANIZATION: "#8b5cf6",
  PLACE: "#10b981",
  CONCEPT: "#f59e0b",
  EVENT: "#ef4444",
  TECHNOLOGY: "#06b6d4",
  DATE: "#6b7280",
}

const DEFAULT_COLOR = "#94a3b8"
const DIM_COLOR = "rgba(200,200,200,0.15)"

interface GraphNode {
  id: string
  label: string
  type: string
  size: number
}

interface GraphEdge {
  source: string
  target: string
  weight: number
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
}

async function fetchGraphData(
  documentId: string | null,
  scope: "document" | "all",
  viewMode: "knowledge_graph" | "call_graph" = "knowledge_graph",
): Promise<GraphData> {
  const url =
    scope === "document" && documentId
      ? `${API_BASE}/graph/${documentId}?type=${viewMode}`
      : `${API_BASE}/graph?doc_ids=`
  const res = await fetch(url)
  if (!res.ok) throw new Error("Failed to fetch graph data")
  return res.json() as Promise<GraphData>
}

function buildGraph(nodes: GraphNode[], edges: GraphEdge[]): Graph {
  const g = new Graph()
  const frequencies = nodes.map((n) => n.size)
  const minFreq = Math.min(...frequencies, 1)
  const maxFreq = Math.max(...frequencies, 1)
  const scaleSize = (freq: number) =>
    maxFreq === minFreq ? 10 : 4 + ((freq - minFreq) / (maxFreq - minFreq)) * 16

  nodes.forEach((node) => {
    g.addNode(node.id, {
      label: node.label,
      type: node.type,
      frequency: node.size,
      x: Math.random() * 200 - 100,
      y: Math.random() * 200 - 100,
      size: scaleSize(node.size),
      color: TYPE_COLORS[node.type as EntityType] ?? DEFAULT_COLOR,
    })
  })

  edges.forEach((edge, idx) => {
    if (g.hasNode(edge.source) && g.hasNode(edge.target) && edge.source !== edge.target) {
      if (!g.hasEdge(edge.source, edge.target)) {
        g.addEdge(edge.source, edge.target, { key: `e-${idx}`, weight: edge.weight ?? 1 })
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

// ---- Inner component: event handler (must be inside SigmaContainer) ----

interface GraphControllerProps {
  search: string
  onNodeClick: (nodeId: string, screenX: number, screenY: number) => void
  onEdgeHover: (label: string | null) => void
}

function GraphController({ search, onNodeClick, onEdgeHover }: GraphControllerProps) {
  const sigma = useSigma()
  const setSettings = useSetSettings()
  const registerEvents = useRegisterEvents()

  useEffect(() => {
    if (!search) {
      setSettings({ nodeReducer: null, edgeReducer: null })
      return
    }
    const q = search.toLowerCase()
    setSettings({
      nodeReducer: (_nodeKey, data) => {
        const label = (data.label as string) ?? ""
        if (label.toLowerCase().includes(q)) return data
        return { ...data, color: DIM_COLOR, label: "" }
      },
      edgeReducer: (_edgeKey, data) => ({ ...data, color: DIM_COLOR }),
    })

    // Pan camera to first matching node
    const graph = sigma.getGraph()
    const firstMatch = graph.nodes().find((n) => {
      const lbl = (graph.getNodeAttribute(n, "label") as string) ?? ""
      return lbl.toLowerCase().includes(q)
    })
    if (firstMatch) {
      const x = graph.getNodeAttribute(firstMatch, "x") as number
      const y = graph.getNodeAttribute(firstMatch, "y") as number
      sigma.getCamera().animate({ x, y, ratio: 0.5 }, { duration: 500 })
    }
  }, [search, sigma, setSettings])

  useEffect(() => {
    registerEvents({
      clickNode: (payload: SigmaNodeEventPayload) => {
        const { node, event } = payload
        const pos = sigma.graphToViewport({
          x: sigma.getGraph().getNodeAttribute(node, "x") as number,
          y: sigma.getGraph().getNodeAttribute(node, "y") as number,
        })
        const rect = sigma.getContainer().getBoundingClientRect()
        onNodeClick(node, rect.left + pos.x, rect.top + pos.y)
        event.preventSigmaDefault()
      },
      enterEdge: (payload: SigmaEdgeEventPayload) => {
        const { edge } = payload
        const edgeType =
          (sigma.getGraph().getEdgeAttribute(edge, "type") as string | undefined) ?? "CO_OCCURS"
        onEdgeHover(edgeType)
      },
      leaveEdge: () => onEdgeHover(null),
      clickStage: () => onNodeClick("", -1, -1),
    })
  }, [registerEvents, sigma, onNodeClick, onEdgeHover])

  return null
}

// ---- Camera controls (must be inside SigmaContainer) ----

function CameraControls() {
  const { zoomIn, zoomOut, reset } = useCamera({ duration: 300, factor: 1.5 })

  return (
    <div className="absolute bottom-4 right-4 flex flex-col gap-1 z-10">
      <button
        onClick={() => zoomIn()}
        className="flex h-8 w-8 items-center justify-center rounded border border-border bg-background text-foreground shadow-sm hover:bg-accent"
        title="Zoom in"
      >
        <Plus size={14} />
      </button>
      <button
        onClick={() => zoomOut()}
        className="flex h-8 w-8 items-center justify-center rounded border border-border bg-background text-foreground shadow-sm hover:bg-accent"
        title="Zoom out"
      >
        <Minus size={14} />
      </button>
      <button
        onClick={() => reset()}
        className="flex h-8 w-8 items-center justify-center rounded border border-border bg-background text-foreground shadow-sm hover:bg-accent"
        title="Fit to screen"
      >
        <Maximize2 size={14} />
      </button>
    </div>
  )
}

// ---- Main Viz page ----

export default function Viz() {
  const activeDocumentId = useAppStore((s) => s.activeDocumentId)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const mountTime = useRef(Date.now())

  useEffect(() => {
    logger.info("[Viz] mounted")
  }, [])

  const [activeTypes, setActiveTypes] = useState<Set<EntityType>>(new Set(ALL_ENTITY_TYPES))
  const [search, setSearch] = useState("")
  const [scope, setScope] = useState<"document" | "all">("document")
  const [viewMode, setViewMode] = useState<"knowledge_graph" | "call_graph">("knowledge_graph")
  const [selectedNode, setSelectedNode] = useState<SelectedNodeInfo | null>(null)
  const [edgeTooltip, setEdgeTooltip] = useState<string | null>(null)

  const noDocSelected = scope === "document" && !activeDocumentId

  const queryKey = ["graph", scope, activeDocumentId, viewMode]
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey,
    queryFn: () => fetchGraphData(activeDocumentId, scope, viewMode),
    staleTime: 30_000,
    enabled: !noDocSelected,
  })

  useEffect(() => {
    if (!isLoading && data) {
      const elapsed = Date.now() - mountTime.current
      logger.info("[Viz] loaded", { duration_ms: elapsed, itemCount: data.nodes.length })
    }
  }, [isLoading, data])

  useEffect(() => {
    if (isError) {
      logger.error("[Viz] fetch failed", { endpoint: `/graph/${activeDocumentId ?? "all"}` })
    }
  }, [isError, activeDocumentId])

  const filteredGraph = useMemo(() => {
    if (!data) return null
    const visibleNodes = data.nodes.filter((n) => activeTypes.has(n.type as EntityType))
    const visibleIds = new Set(visibleNodes.map((n) => n.id))
    const visibleEdges = data.edges.filter(
      (e) => visibleIds.has(e.source) && visibleIds.has(e.target),
    )
    return buildGraph(visibleNodes, visibleEdges)
  }, [data, activeTypes])

  const handleNodeClick = (nodeId: string, screenX: number, screenY: number) => {
    if (!nodeId || !filteredGraph) {
      setSelectedNode(null)
      return
    }
    setSelectedNode({
      id: nodeId,
      label: filteredGraph.getNodeAttribute(nodeId, "label") as string,
      type: filteredGraph.getNodeAttribute(nodeId, "type") as string,
      frequency: filteredGraph.getNodeAttribute(nodeId, "frequency") as number,
      screenX,
      screenY,
    })
  }

  const toggleType = (type: EntityType) => {
    setActiveTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  if (noDocSelected) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
        <p className="text-sm text-muted-foreground max-w-sm">
          Select a document to explore its knowledge graph.
        </p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex h-full flex-col gap-4 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="flex-1 w-full rounded-lg" />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex h-full items-center justify-center p-6">
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
    )
  }

  if (!data || data.nodes.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
        <Network size={32} className="text-muted-foreground/50" />
        <p className="text-base font-medium text-foreground">No knowledge graph yet</p>
        <p className="text-sm text-muted-foreground max-w-sm">
          Select a document above and ingest it first to see entity relationships.
        </p>
      </div>
    )
  }

  return (
    <div className="flex h-full w-full overflow-hidden">
      {/* Controls sidebar */}
      <div className="w-60 flex-shrink-0 flex flex-col gap-4 border-r border-border bg-background p-4 overflow-y-auto">
        {/* View toggle — Knowledge Graph vs Call Graph */}
        <div>
          <p className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            View
          </p>
          <div className="flex rounded-md border border-border overflow-hidden text-xs">
            {(["knowledge_graph", "call_graph"] as const).map((v) => (
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
                {v === "knowledge_graph" ? "Knowledge" : "Call Graph"}
              </button>
            ))}
          </div>
          {viewMode === "call_graph" && (
            <p className="mt-1 text-xs text-muted-foreground">Code documents only</p>
          )}
        </div>

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

      {/* Graph area */}
      <div className="relative flex-1 overflow-hidden">
        {filteredGraph && (
          <SigmaContainer
            graph={filteredGraph}
            style={{ height: "100%", width: "100%" }}
            settings={{
              renderEdgeLabels: false,
              defaultEdgeColor: "#e2e8f0",
              labelSize: 12,
              labelWeight: "normal",
            }}
          >
            <GraphController
              search={search}
              onNodeClick={handleNodeClick}
              onEdgeHover={setEdgeTooltip}
            />
            <CameraControls />
          </SigmaContainer>
        )}

        {/* Node click popover */}
        {selectedNode && (
          <div
            className="fixed z-50 rounded-lg border border-border bg-background shadow-lg p-3 min-w-[180px]"
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
            <p className="text-xs text-muted-foreground mb-2">
              Mentions: {selectedNode.frequency}
            </p>
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
  )
}
