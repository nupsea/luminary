// Visual maps for confidence/transparency badges and strategy labels.

import type { Confidence } from "./types"

export const CONFIDENCE_BADGE: Record<Confidence, "green" | "blue" | "gray"> = {
  high: "green",
  medium: "blue",
  low: "gray",
}

// transparency badge uses green/yellow/red per AC (not the shadcn Badge variant system)
export const TRANSPARENCY_BADGE_CLASS: Record<string, string> = {
  high: "bg-green-100 text-green-800 border border-green-200 dark:bg-green-950/40 dark:text-green-300 dark:border-green-900",
  medium: "bg-yellow-100 text-yellow-800 border border-yellow-200 dark:bg-yellow-950/40 dark:text-yellow-300 dark:border-yellow-900",
  low: "bg-red-100 text-red-800 border border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900",
}

export const STRATEGY_LABEL: Record<string, string> = {
  executive_summary: "Executive summary",
  hybrid_retrieval: "Hybrid retrieval (vector + keyword)",
  graph_traversal: "Graph traversal",
  comparative: "Comparative search",
  augmented_hybrid: "Augmented hybrid retrieval",
}
