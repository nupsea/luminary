// Pure graphology builders for the Viz page. These translate the
// API responses into a renderable Graph object (positions assigned
// via ForceAtlas2). No React; the Sigma instance in Viz.tsx
// receives the result and renders it.

import Graph from "graphology"
import forceAtlas2 from "graphology-layout-forceatlas2"

import { noteNodeAttrs } from "@/lib/noteGraphUtils"
import type { ClusterNodeDef, EntityType } from "@/lib/vizUtils"

import {
  DEFAULT_COLOR,
  LINKS_TO_EDGE_COLOR,
  LP_EDGE_COLOR,
  PREREQ_EDGE_COLOR,
  SAME_CONCEPT_COLOR,
  SAME_CONCEPT_CONTRADICTION_COLOR,
  TYPE_COLORS,
  WRITTEN_ABOUT_EDGE_COLOR,
} from "./constants"
import type { GraphEdge, GraphNode, LearningPathData, LearningPathNode } from "./types"

/** Build the main viz graph: entity + diagram + note nodes, all
 *  edge categories (CO_OCCURS / PREREQUISITE_OF / SAME_CONCEPT /
 *  WRITTEN_ABOUT / TAG_IS_CONCEPT / LINKS_TO).
 */
export function buildGraph(nodes: GraphNode[], edges: GraphEdge[]): Graph {
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

/** Learning path graph (S117): directed graphology graph with
 *  vertical depth-based layout so deeper prerequisites sit lower. */
export function buildLearningPathGraph(data: LearningPathData): Graph {
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

/** Cluster graph (S181): non-expanded entity types collapse into
 *  single cluster nodes; expanded types and note nodes render
 *  individually. */
export function buildClusterGraphology(
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
