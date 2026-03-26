// ---------------------------------------------------------------------------
// Viz tab pure utility functions (S181)
// No Sigma/DOM/Graphology imports -- safe for Vitest node environment.
// ---------------------------------------------------------------------------

export const ALL_ENTITY_TYPES = [
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
  // Diagram-derived types (S136)
  "COMPONENT",
  "ACTOR",
  "ENTITY_DM",
  "STEP",
] as const

export type EntityType = (typeof ALL_ENTITY_TYPES)[number]

// Minimal node shape used by pure utility functions.
export interface VizNodeBase {
  id: string
  label: string
  type: string
  size: number
  source_image_id?: string
  note_id?: string
  outgoing_link_count?: number
}

// ---------------------------------------------------------------------------
// Code document detection
// ---------------------------------------------------------------------------

const CODE_FORMATS: ReadonlySet<string> = new Set([
  "code",
  "py", "js", "ts", "jsx", "tsx",
  "java", "cpp", "c", "go", "rs",
  "rb", "php", "cs", "swift", "kt",
])

/**
 * Returns true when the document is a code document based on its format field.
 * The format field from the documents API contains either the canonical "code"
 * value or an inferred file extension (e.g., "py", "ts").
 */
export function isCodeDocument(format: string, contentType?: string): boolean {
  if (CODE_FORMATS.has(format.toLowerCase())) return true
  if (contentType === "code") return true
  return false
}

// ---------------------------------------------------------------------------
// Cluster view helpers
// ---------------------------------------------------------------------------

/**
 * Returns true when cluster view should be active:
 * the toggle is enabled AND the non-note entity count exceeds 200.
 */
export function shouldShowClusterView(nodes: VizNodeBase[], enabled: boolean): boolean {
  if (!enabled) return false
  return nodes.filter((n) => n.type !== "note").length > 200
}

/** Descriptor for one cluster node (no Graphology dependency). */
export interface ClusterNodeDef {
  clusterId: string     // e.g. "cluster:CONCEPT"
  entityType: string    // e.g. "CONCEPT"
  count: number
  label: string         // e.g. "CONCEPT (42)"
}

/**
 * Groups non-expanded, non-note nodes by entity type into cluster descriptors.
 * Nodes whose type is in `expandedTypes` are NOT clustered -- they render
 * as individual nodes in the caller.
 */
export function buildClusterNodes(
  nodes: VizNodeBase[],
  expandedTypes: Set<string>,
): ClusterNodeDef[] {
  const groups = new Map<string, number>()
  for (const node of nodes) {
    if (node.type === "note") continue
    if (expandedTypes.has(node.type)) continue
    groups.set(node.type, (groups.get(node.type) ?? 0) + 1)
  }
  return [...groups.entries()].map(([entityType, count]) => ({
    clusterId: `cluster:${entityType}`,
    entityType,
    count,
    label: `${entityType} (${count})`,
  }))
}
