// Pure presentation helpers for the Viz page.

/** Map a 0..1 mastery score to a sigma node colour for the
 *  retention overlay. */
export function masteryColor(mastery: number): string {
  if (mastery >= 0.7) return "#22c55e" // green-500: strong
  if (mastery >= 0.4) return "#84cc16" // lime-500: good
  if (mastery >= 0.15) return "#f97316" // orange-500: weak
  return "#ef4444" // red-500: critical
}

/**
 * Resolve the target document ID for a graph node when navigating.
 *
 * If activeDocumentId is in the node's document_ids, stay in activeDocumentId.
 * Otherwise prefer node.document_id, or the first document in node.document_ids,
 * or fall back to activeDocumentId.
 */
export function resolveNodeTargetDocument(
  node: { document_id?: string; document_ids?: string[] },
  activeDocumentId: string | null,
): string | null {
  if (activeDocumentId && node.document_ids?.includes(activeDocumentId)) {
    return activeDocumentId
  }
  if (node.document_id) {
    return node.document_id
  }
  if (node.document_ids && node.document_ids.length > 0) {
    return node.document_ids[0]
  }
  return activeDocumentId
}

/**
 * Format the "Find in document" navigation URL for a graph node.
 */
export function getNodeFindInDocUrl(
  node: { label: string; document_id?: string; document_ids?: string[] },
  activeDocumentId: string | null,
): string {
  const docId = resolveNodeTargetDocument(node, activeDocumentId)
  if (docId) {
    return `/library?doc=${encodeURIComponent(docId)}&search=${encodeURIComponent(node.label)}`
  }
  return `/library?search=${encodeURIComponent(node.label)}`
}

