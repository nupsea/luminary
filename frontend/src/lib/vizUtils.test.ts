import { describe, it, expect } from "vitest"
import { isCodeDocument, shouldShowClusterView, buildClusterNodes } from "./vizUtils"
import type { VizNodeBase } from "./vizUtils"

// ---------------------------------------------------------------------------
// isCodeDocument
// ---------------------------------------------------------------------------

describe("isCodeDocument", () => {
  it("returns true for canonical code format", () => {
    expect(isCodeDocument("code", "book")).toBe(true)
  })

  it("returns false for pdf book document", () => {
    expect(isCodeDocument("pdf", "book")).toBe(false)
  })

  it("returns true for py extension (python file)", () => {
    expect(isCodeDocument("py", "tech_article")).toBe(true)
  })

  it("returns true for ts extension", () => {
    expect(isCodeDocument("ts")).toBe(true)
  })

  it("returns true for go extension", () => {
    expect(isCodeDocument("go")).toBe(true)
  })

  it("returns false for txt format", () => {
    expect(isCodeDocument("txt", "notes")).toBe(false)
  })

  it("returns false for md format", () => {
    expect(isCodeDocument("md")).toBe(false)
  })

  it("is case-insensitive for format", () => {
    expect(isCodeDocument("PY")).toBe(true)
    expect(isCodeDocument("CODE")).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// shouldShowClusterView
// ---------------------------------------------------------------------------

function makeNodes(count: number, type = "CONCEPT"): VizNodeBase[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `n${i}`,
    label: `N${i}`,
    type,
    size: 1,
  }))
}

describe("shouldShowClusterView", () => {
  it("returns false when cluster toggle is disabled", () => {
    expect(shouldShowClusterView(makeNodes(300), false)).toBe(false)
  })

  it("returns true when enabled and entity count > 200", () => {
    expect(shouldShowClusterView(makeNodes(201), true)).toBe(true)
  })

  it("returns false when enabled but entity count equals 200", () => {
    expect(shouldShowClusterView(makeNodes(200), true)).toBe(false)
  })

  it("returns false when enabled but entity count < 200", () => {
    expect(shouldShowClusterView(makeNodes(50), true)).toBe(false)
  })

  it("excludes note nodes from the entity count", () => {
    const nodes: VizNodeBase[] = [
      ...makeNodes(199),
      { id: "note1", label: "A Note", type: "note", size: 1 },
      { id: "note2", label: "B Note", type: "note", size: 1 },
    ]
    // 199 entity nodes + 2 note nodes = 201 total, but only 199 non-note
    expect(shouldShowClusterView(nodes, true)).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// buildClusterNodes
// ---------------------------------------------------------------------------

describe("buildClusterNodes", () => {
  it("groups nodes by entity type", () => {
    const nodes: VizNodeBase[] = [
      { id: "1", label: "A", type: "CONCEPT", size: 1 },
      { id: "2", label: "B", type: "CONCEPT", size: 1 },
      { id: "3", label: "C", type: "PERSON", size: 1 },
    ]
    const clusters = buildClusterNodes(nodes, new Set())
    expect(clusters).toHaveLength(2)
    const conceptCluster = clusters.find((c) => c.entityType === "CONCEPT")
    expect(conceptCluster).toBeDefined()
    expect(conceptCluster?.count).toBe(2)
    expect(conceptCluster?.clusterId).toBe("cluster:CONCEPT")
    expect(conceptCluster?.label).toBe("CONCEPT (2)")
  })

  it("excludes nodes whose type is in expandedTypes", () => {
    const nodes: VizNodeBase[] = [
      { id: "1", label: "A", type: "CONCEPT", size: 1 },
      { id: "2", label: "C", type: "PERSON", size: 1 },
    ]
    const clusters = buildClusterNodes(nodes, new Set(["CONCEPT"]))
    expect(clusters).toHaveLength(1)
    expect(clusters[0].entityType).toBe("PERSON")
  })

  it("excludes note nodes entirely", () => {
    const nodes: VizNodeBase[] = [
      { id: "1", label: "A Note", type: "note", size: 1 },
    ]
    expect(buildClusterNodes(nodes, new Set())).toHaveLength(0)
  })

  it("returns empty array when all nodes are expanded or notes", () => {
    const nodes: VizNodeBase[] = [
      { id: "1", label: "A", type: "CONCEPT", size: 1 },
      { id: "2", label: "B", type: "note", size: 1 },
    ]
    expect(buildClusterNodes(nodes, new Set(["CONCEPT"]))).toHaveLength(0)
  })

  it("returns clusterId in cluster:TYPE format", () => {
    const nodes: VizNodeBase[] = [
      { id: "1", label: "A", type: "TECHNOLOGY", size: 1 },
    ]
    const [cluster] = buildClusterNodes(nodes, new Set())
    expect(cluster.clusterId).toBe("cluster:TECHNOLOGY")
  })
})
