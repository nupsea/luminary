// Pure presentation helpers used by Study sub-components.
// No state, no fetches, no React -- safe to import anywhere.

/** Tailwind class for the coverage badge based on score 0..1. */
export function coverageBadgeClass(score: number): string {
  if (score >= 0.7) return "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
  if (score >= 0.4) return "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200"
  return "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
}

/** Bloom-bar fill colour by taxonomy level (1..6). */
export function bloomBarFill(level: number): string {
  if (level <= 2) return "#94a3b8" // muted gray: remember/understand
  if (level <= 4) return "#3b82f6" // blue: apply/analyze
  return "#8b5cf6" // purple: evaluate/create
}

/** Tailwind class for the "fragile cards" bar by avg FSRS stability (days). */
export function fragileBarColor(avgStability: number): string {
  if (avgStability < 2) return "bg-red-500"
  if (avgStability <= 5) return "bg-amber-400"
  return "bg-green-500"
}
