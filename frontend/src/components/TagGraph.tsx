/**
 * TagGraph component (S167)
 *
 * Renders a Sigma.js + Graphology co-occurrence network of canonical tags.
 * Node click dispatches 'luminary:navigate' to cross-navigate to Notes tab.
 */

import Graph from "graphology"
import forceAtlas2 from "graphology-layout-forceatlas2"
import { useEffect, useRef } from "react"
import Sigma from "sigma"
import type { SigmaNodeEventPayload } from "sigma/types"
import {
  buildNavigateEvent,
  colorFromParentTag,
  edgeWidthFromWeight,
  nodeSizeFromCount,
  TAG_GRAPH_PALETTE,
} from "@/lib/tagGraphUtils"
import { logger } from "@/lib/logger"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TagNodeData {
  id: string
  display_name: string
  parent_tag: string | null
  note_count: number
}

export interface TagEdgeData {
  tag_a: string
  tag_b: string
  weight: number
}

interface TagGraphProps {
  nodes: TagNodeData[]
  edges: TagEdgeData[]
  isLoading: boolean
  isError: boolean
  onRetry: () => void
}

// ---------------------------------------------------------------------------
// Graph builder
// ---------------------------------------------------------------------------

function buildTagGraphology(nodes: TagNodeData[], edges: TagEdgeData[]): Graph {
  const g = new Graph({ type: "undirected", multi: false })

  const maxWeight = edges.reduce((m, e) => Math.max(m, e.weight), 1)

  nodes.forEach((node) => {
    if (!g.hasNode(node.id)) {
      g.addNode(node.id, {
        label: node.display_name,
        noteCount: node.note_count,
        parentTag: node.parent_tag,
        x: Math.random() * 200 - 100,
        y: Math.random() * 200 - 100,
        size: nodeSizeFromCount(node.note_count),
        color: colorFromParentTag(node.parent_tag, TAG_GRAPH_PALETTE),
      })
    }
  })

  edges.forEach((edge, idx) => {
    if (g.hasNode(edge.tag_a) && g.hasNode(edge.tag_b)) {
      if (!g.hasEdge(edge.tag_a, edge.tag_b)) {
        g.addEdge(edge.tag_a, edge.tag_b, {
          key: `tg-e-${idx}`,
          weight: edge.weight,
          size: edgeWidthFromWeight(edge.weight, maxWeight),
          color: "#e2e8f0",
        })
      }
    }
  })

  if (g.order > 0) {
    forceAtlas2.assign(g, {
      iterations: 50,
      settings: forceAtlas2.inferSettings(g),
    })
  }

  return g
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TagGraph({ nodes, edges, isLoading, isError, onRetry }: TagGraphProps) {
  const canvasRef = useRef<HTMLDivElement>(null)
  const sigmaRef = useRef<Sigma | null>(null)

  // Build Sigma whenever nodes/edges change
  useEffect(() => {
    const el = canvasRef.current
    if (!el) return

    if (sigmaRef.current) {
      sigmaRef.current.kill()
      sigmaRef.current = null
    }

    if (isLoading || isError || nodes.length < 3) {
      el.innerHTML = ""
      return
    }

    const g = buildTagGraphology(nodes, edges)
    if (g.order === 0) {
      el.innerHTML = ""
      return
    }

    // Clean container explicitly
    el.innerHTML = ""

    const s = new Sigma(g, el, {
      renderEdgeLabels: false,
      defaultEdgeColor: "#e2e8f0",
      labelSize: 11,
      labelWeight: "normal",
      allowInvalidContainer: true,
    })

    // WebGL context lost/restored handlers
    const canvases = el.querySelectorAll("canvas")
    const handleContextLost = (e: Event) => {
      e.preventDefault()
      logger.warn("[TagGraph] WebGL context lost")
    }
    const handleContextRestored = () => {
      logger.info("[TagGraph] WebGL context restored")
      try { s.refresh() } catch { /* sigma may be killed */ }
    }
    canvases.forEach((c) => {
      c.addEventListener("webglcontextlost", handleContextLost)
      c.addEventListener("webglcontextrestored", handleContextRestored)
    })

    // Node click -> dispatch cross-tab navigation event
    s.on("clickNode", (payload: SigmaNodeEventPayload) => {
      const ev = buildNavigateEvent(payload.node)
      window.dispatchEvent(ev)
    })

    sigmaRef.current = s

    return () => {
      canvases.forEach((c) => {
        c.removeEventListener("webglcontextlost", handleContextLost)
        c.removeEventListener("webglcontextrestored", handleContextRestored)
      })
      s.kill()
      sigmaRef.current = null
      if (el) el.innerHTML = ""
    }
  }, [nodes, edges, isLoading, isError])

  // ---------------------------------------------------------------------------
  // Loading state
  // ---------------------------------------------------------------------------
  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div
          className="h-8 w-8 rounded-full border-2 border-primary border-t-transparent"
          style={{ animation: "spin 0.8s linear infinite" }}
          role="status"
          aria-label="Loading tag graph"
        />
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // Error state
  // ---------------------------------------------------------------------------
  if (isError) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="flex flex-col items-center gap-3 rounded-md border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700">
          <p className="font-medium">Failed to load tag graph</p>
          <button
            onClick={onRetry}
            className="rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs text-red-700 hover:bg-red-50 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // Empty state
  // ---------------------------------------------------------------------------
  if (nodes.length < 3) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-center p-6">
        <p className="text-base font-semibold text-foreground">Not enough tagged notes</p>
        <p className="text-sm text-muted-foreground max-w-xs">
          Add at least 3 tagged notes to see the tag network. Tags that appear together on the same
          note will be connected by edges.
        </p>
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // Graph canvas
  // ---------------------------------------------------------------------------
  return (
    <div ref={canvasRef} style={{ width: "100%", height: "100%" }} />
  )
}
