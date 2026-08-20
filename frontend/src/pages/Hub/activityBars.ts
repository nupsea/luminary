/**
 * The week's time split, as labelled bars.
 *
 * Bars rather than a pie: four magnitudes compared against each other is what
 * a bar chart is for, and a pie of four wedges made the smallest slices
 * unreadable at 72px. Identity comes from the row label, so the bars need no
 * categorical palette -- one accent carries all four, which is also what
 * removed the muddy four-hue set this replaced.
 */
export interface ActivityBar {
  key: string
  label: string
  seconds: number
  /** Share of the widest bar, 0-100. Relative, so a quiet week still reads. */
  pct: number
}

const ORDER: { key: string; label: string }[] = [
  { key: "document", label: "Reading" },
  { key: "study", label: "Study" },
  { key: "note", label: "Notes" },
  { key: "review", label: "Review" },
]

/**
 * Bars in fixed order, scaled against the largest.
 *
 * Scaled to the maximum rather than the total because the question the row
 * answers is "where did the week go", and against a total a 4% slice is a
 * sliver indistinguishable from nothing recorded.
 */
export function buildBars(byActivity: Record<string, number>): {
  bars: ActivityBar[]
  total: number
} {
  const withSeconds = ORDER.map((o) => ({
    ...o,
    seconds: Math.max(0, byActivity[o.key] ?? 0),
  }))
  const total = withSeconds.reduce((sum, b) => sum + b.seconds, 0)
  const max = Math.max(...withSeconds.map((b) => b.seconds), 0)
  return {
    bars: withSeconds.map((b) => ({
      ...b,
      pct: max > 0 && b.seconds > 0 ? Math.max(3, Math.round((b.seconds / max) * 100)) : 0,
    })),
    total,
  }
}
