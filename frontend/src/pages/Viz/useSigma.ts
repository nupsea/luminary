// useSigma -- React hook owning the Sigma instance lifecycle for the
// Viz canvas. Encapsulates:
//
//   - canvasRef + sigmaRef + WebGL context-loss recovery
//   - the rebuild-on-graph-change effect, including click/hover wiring
//     and the slight setTimeout that gives a previous WebGL context a
//     chance to be reclaimed before constructing a new instance
//   - the search/retention nodeReducer + edgeReducer effect
//   - camera control callbacks (zoom in / out / reset)
//
// Returns the canvas ref to spread on the host <div>, plus the three
// camera handlers. The host calls back via the on* callbacks when a
// click/hover event needs to update React state in the parent.

import type Graph from "graphology"
import { useEffect, useRef } from "react"
import Sigma from "sigma"
import type { SigmaEdgeEventPayload, SigmaNodeEventPayload } from "sigma/types"

import { logger } from "@/lib/logger"
import NodeHexagonProgram from "@/lib/sigma-hexagon"
import NodeSquareProgram from "@/lib/sigma-square"

import { BLIND_SPOT_COLOR, DIM_COLOR, LP_EDGE_COLOR } from "./constants"
import type { MasteryConceptItem, SelectedNodeInfo } from "./types"
import { masteryColor } from "./utils"

interface UseSigmaOptions {
  filteredGraph: Graph | null
  viewMode: string
  search: string
  showRetention: boolean
  masteryMap: Map<string, MasteryConceptItem>
  onSelectNode: (info: SelectedNodeInfo | null) => void
  onSelectNoteId: (id: string | null) => void
  onEdgeHover: (label: string | null) => void
  onClusterToggle: (clusterEntityType: string) => void
}

interface UseSigmaResult {
  canvasRef: React.RefObject<HTMLDivElement | null>
  zoomIn: () => void
  zoomOut: () => void
  resetCamera: () => void
}

export function useSigma(opts: UseSigmaOptions): UseSigmaResult {
  const {
    filteredGraph,
    viewMode,
    search,
    showRetention,
    masteryMap,
    onSelectNode,
    onSelectNoteId,
    onEdgeHover,
    onClusterToggle,
  } = opts

  const canvasRef = useRef<HTMLDivElement>(null)
  const sigmaRef = useRef<Sigma | null>(null)
  // Track whether we need to rebuild sigma after a WebGL context restore
  const pendingRestoreRef = useRef(false)

  // -------------------------------------------------------------------------
  // Rebuild Sigma whenever filteredGraph changes
  // -------------------------------------------------------------------------
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
      const currentEl = canvasRef.current
      if (!currentEl) return

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

      const canvases = currentEl.querySelectorAll("canvas")
      const handleContextLost = (e: Event) => {
        e.preventDefault()
        logger.warn("[Viz] WebGL context lost -- will restore on recovery")
        pendingRestoreRef.current = true
      }
      const handleContextRestored = () => {
        logger.info("[Viz] WebGL context restored -- refreshing sigma")
        pendingRestoreRef.current = false
        try {
          s.refresh()
        } catch {
          logger.warn("[Viz] sigma refresh failed")
        }
      }
      canvases.forEach((c) => {
        c.addEventListener("webglcontextlost", handleContextLost)
        c.addEventListener("webglcontextrestored", handleContextRestored)
      })

      s.on("clickNode", (payload: SigmaNodeEventPayload) => {
        const { node, event } = payload
        const entityType = filteredGraph.getNodeAttribute(node, "entityType") as string

        const isCluster = filteredGraph.getNodeAttribute(node, "isCluster") as
          | boolean
          | undefined
        if (isCluster) {
          const clusterEntityType = filteredGraph.getNodeAttribute(
            node,
            "clusterEntityType",
          ) as string
          onClusterToggle(clusterEntityType)
          event.preventSigmaDefault()
          return
        }

        if (entityType === "note") {
          const noteId =
            (filteredGraph.getNodeAttribute(node, "note_id") as string | undefined) ?? node
          onSelectNode(null)
          onSelectNoteId(noteId)
          event.preventSigmaDefault()
          return
        }

        const pos = s.graphToViewport({
          x: filteredGraph.getNodeAttribute(node, "x") as number,
          y: filteredGraph.getNodeAttribute(node, "y") as number,
        })
        const rect = currentEl.getBoundingClientRect()
        onSelectNoteId(null)
        onSelectNode({
          id: node,
          label: filteredGraph.getNodeAttribute(node, "label") as string,
          type: entityType,
          frequency: filteredGraph.getNodeAttribute(node, "frequency") as number,
          screenX: rect.left + pos.x,
          screenY: rect.top + pos.y,
          source_image_id:
            (filteredGraph.getNodeAttribute(node, "source_image_id") as string | undefined) ??
            "",
        })
        event.preventSigmaDefault()
      })

      s.on("enterEdge", (payload: SigmaEdgeEventPayload) => {
        const edgeType =
          (filteredGraph.getEdgeAttribute(payload.edge, "type") as string | undefined) ??
          "CO_OCCURS"
        onEdgeHover(edgeType)
      })
      s.on("leaveEdge", () => onEdgeHover(null))

      s.on("clickStage", () => {
        onSelectNode(null)
        onSelectNoteId(null)
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- callbacks are stable per render in caller
  }, [filteredGraph])

  // -------------------------------------------------------------------------
  // Search + retention overlay reducer effect (must compose in one effect)
  // -------------------------------------------------------------------------
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
      const label = (d.label as string) ?? ""
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

    s.setSetting(
      "edgeReducer",
      hasSearch
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
  }, [search, filteredGraph, showRetention, masteryMap])

  // -------------------------------------------------------------------------
  // Camera controls
  // -------------------------------------------------------------------------
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
    sigmaRef.current
      ?.getCamera()
      .animate({ x: 0.5, y: 0.5, ratio: 1, angle: 0 }, { duration: 300 })
  }

  return { canvasRef, zoomIn, zoomOut, resetCamera }
}
