/**
 * The week's time split, as a pie.
 *
 * Colours are a categorical set validated against both card surfaces rather
 * than chosen by eye: `#0c0f18` dark (`--card` at 222 35% 7%) and `#ffffff`
 * light. The set they replace failed the lightness band -- its green sat at
 * L 0.699 and its amber at L 0.776 against a 0.48-0.67 band -- so four wedges
 * that should read at one visual weight did not, which is what made the chart
 * look muddy. Identity is never colour alone: every wedge is also a labelled
 * legend row carrying its own duration.
 */
export interface ActivitySlice {
  key: string
  label: string
  colour: string
}

export const ACTIVITY_SLICES: ActivitySlice[] = [
  { key: "document", label: "Reading", colour: "#3987e5" },
  { key: "note", label: "Notes", colour: "#d95926" },
  { key: "review", label: "Review", colour: "#199e70" },
  { key: "study", label: "Study", colour: "#c98500" },
]

export interface Wedge {
  key: string
  label: string
  colour: string
  seconds: number
  /** SVG path for the wedge, or null when it is the only one and fills the circle. */
  path: string | null
}

function point(cx: number, cy: number, r: number, angle: number): string {
  return `${(cx + r * Math.cos(angle)).toFixed(3)} ${(cy + r * Math.sin(angle)).toFixed(3)}`
}

/** A filled wedge from `start` to `end`, both in radians clockwise from noon. */
export function slicePath(cx: number, cy: number, r: number, start: number, end: number): string {
  const large = end - start > Math.PI ? 1 : 0
  return `M ${cx} ${cy} L ${point(cx, cy, r, start)} A ${r} ${r} 0 ${large} 1 ${point(cx, cy, r, end)} Z`
}

/**
 * Wedges for the slices that have time in them, starting at noon.
 *
 * A slice of zero gets no wedge -- a zero-width path renders as a hairline
 * artefact, and the legend is where "nothing this week" is said.
 */
export function buildWedges(
  byActivity: Record<string, number>,
  cx: number,
  cy: number,
  r: number,
): { wedges: Wedge[]; total: number } {
  const withSeconds = ACTIVITY_SLICES.map((s) => ({
    ...s,
    seconds: Math.max(0, byActivity[s.key] ?? 0),
  }))
  const total = withSeconds.reduce((sum, s) => sum + s.seconds, 0)
  if (total === 0) return { wedges: [], total: 0 }

  const present = withSeconds.filter((s) => s.seconds > 0)
  // One activity fills the circle. Drawn as a circle rather than an arc, whose
  // start and end points coincide and which therefore renders as nothing.
  if (present.length === 1) {
    return { wedges: [{ ...present[0], path: null }], total }
  }

  let angle = -Math.PI / 2
  const wedges: Wedge[] = present.map((slice) => {
    const sweep = (slice.seconds / total) * 2 * Math.PI
    const path = slicePath(cx, cy, r, angle, angle + sweep)
    angle += sweep
    return { ...slice, path }
  })
  return { wedges, total }
}
