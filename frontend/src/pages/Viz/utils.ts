// Pure presentation helpers for the Viz page.

/** Map a 0..1 mastery score to a sigma node colour for the
 *  retention overlay. */
export function masteryColor(mastery: number): string {
  if (mastery >= 0.7) return "#22c55e" // green-500: strong
  if (mastery >= 0.4) return "#84cc16" // lime-500: good
  if (mastery >= 0.15) return "#f97316" // orange-500: weak
  return "#ef4444" // red-500: critical
}
