import { useQuery } from "@tanstack/react-query"
import { SigmaContainer } from "@react-sigma/core"
import Graph from "graphology"
import forceAtlas2 from "graphology-layout-forceatlas2"
import { useAppStore } from "../store"

const API_BASE = "http://localhost:8000"

// Entity type color palette
const TYPE_COLORS: Record<string, string> = {
  PERSON: "#3b82f6",
  ORGANIZATION: "#8b5cf6",
  PLACE: "#10b981",
  CONCEPT: "#f59e0b",
  EVENT: "#ef4444",
  TECHNOLOGY: "#06b6d4",
  DATE: "#6b7280",
}

const DEFAULT_COLOR = "#94a3b8"

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

async function fetchGraphData(documentId: string | null): Promise<GraphData> {
  const url = documentId
    ? `${API_BASE}/graph/${documentId}`
    : `${API_BASE}/graph?doc_ids=`
  const res = await fetch(url)
  if (!res.ok) throw new Error("Failed to fetch graph data")
  return res.json() as Promise<GraphData>
}

function buildGraphologyGraph(data: GraphData): Graph {
  const g = new Graph()

  const frequencies = data.nodes.map((n) => n.size)
  const minFreq = Math.min(...frequencies, 1)
  const maxFreq = Math.max(...frequencies, 1)

  const scaleSize = (freq: number): number => {
    if (maxFreq === minFreq) return 10
    return 4 + ((freq - minFreq) / (maxFreq - minFreq)) * 16
  }

  data.nodes.forEach((node) => {
    g.addNode(node.id, {
      label: node.label,
      x: Math.random() * 200 - 100,
      y: Math.random() * 200 - 100,
      size: scaleSize(node.size),
      color: TYPE_COLORS[node.type] ?? DEFAULT_COLOR,
    })
  })

  data.edges.forEach((edge, idx) => {
    if (g.hasNode(edge.source) && g.hasNode(edge.target) && edge.source !== edge.target) {
      const edgeKey = `e-${idx}`
      if (!g.hasEdge(edge.source, edge.target)) {
        g.addEdge(edge.source, edge.target, { key: edgeKey, weight: edge.weight ?? 1 })
      }
    }
  })

  // Run ForceAtlas2 layout for 100 iterations
  if (g.order > 0) {
    forceAtlas2.assign(g, {
      iterations: 100,
      settings: forceAtlas2.inferSettings(g),
    })
  }

  return g
}

export default function Viz() {
  const activeDocumentId = useAppStore((s) => s.activeDocumentId)

  const { data, isLoading, isError } = useQuery({
    queryKey: ["graph", activeDocumentId],
    queryFn: () => fetchGraphData(activeDocumentId),
    staleTime: 30_000,
  })

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-sm text-muted-foreground">Loading graph...</div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-sm text-destructive">Failed to load graph data.</div>
      </div>
    )
  }

  if (!data || data.nodes.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
        <p className="text-sm text-muted-foreground max-w-sm">
          Ingest a document and wait for entity extraction to complete to see the knowledge graph.
        </p>
      </div>
    )
  }

  const graph = buildGraphologyGraph(data)

  return (
    <div className="h-full w-full">
      <SigmaContainer
        graph={graph}
        style={{ height: "100%", width: "100%" }}
        settings={{
          renderEdgeLabels: false,
          defaultEdgeColor: "#e2e8f0",
          labelSize: 12,
          labelWeight: "normal",
        }}
      />
    </div>
  )
}
