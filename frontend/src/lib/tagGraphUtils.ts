/**
 * Pure utility functions for the tag co-occurrence graph
 * No React/store/DOM imports -- safe for Vitest node environment.
 */

// 12-color palette: one per top-level tag family (hue spread)
export const TAG_GRAPH_PALETTE: string[] = [
  "#3b82f6", // blue-500
  "#ef4444", // red-500
  "#10b981", // emerald-500
  "#f59e0b", // amber-500
  "#8b5cf6", // violet-500
  "#06b6d4", // cyan-500
  "#f97316", // orange-500
  "#84cc16", // lime-500
  "#ec4899", // pink-500
  "#14b8a6", // teal-500
  "#a855f7", // purple-500
  "#6366f1", // indigo-500
]

/**
 * Deterministic color from parent_tag string.
 * Same parent_tag always maps to the same palette entry.
 * Null/empty parent_tag maps to the first palette color.
 */
export function colorFromParentTag(
  parentTag: string | null | undefined,
  palette: string[] = TAG_GRAPH_PALETTE,
): string {
  if (!parentTag) return palette[0]
  let hash = 0
  for (let i = 0; i < parentTag.length; i++) {
    hash = (hash * 31 + parentTag.charCodeAt(i)) >>> 0
  }
  return palette[hash % palette.length]
}

/**
 * Build a 'luminary:navigate' CustomEvent that instructs App.tsx to switch to
 * the Notes tab and apply a tag filter.
 */
export function buildNavigateEvent(tagId: string): CustomEvent {
  return new CustomEvent("luminary:navigate", {
    detail: { tab: "notes", tagFilter: tagId },
    bubbles: true,
    cancelable: true,
  })
}

/**
 * Node size proportional to sqrt(noteCount), clamped to [4, 24].
 * Square-root scaling prevents high-count nodes from dominating.
 */
export function nodeSizeFromCount(noteCount: number): number {
  const raw = Math.sqrt(Math.max(1, noteCount))
  return Math.min(24, Math.max(4, raw * 3))
}

/**
 * Edge width proportional to weight/maxWeight, mapped to [0.5, 4].
 */
export function edgeWidthFromWeight(weight: number, maxWeight: number): number {
  if (maxWeight <= 0) return 0.5
  const ratio = weight / maxWeight
  return 0.5 + ratio * 3.5
}
