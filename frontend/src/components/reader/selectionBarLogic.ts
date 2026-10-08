/** Pure decisions behind SelectionActionBar: which action fits, and where the bar sits. */

/**
 * "lakehouse" and "data lakehouse architecture" are terms to define; "The lakehouse
 * stores tables." or anything past four words is a passage to simplify.
 */
const TERM_MAX_WORDS = 4

export function explainModeFor(text: string): "define" | "plain" {
  const core = text.trim().replace(/[\s.,;:!?"'”’)\]]+$/u, "")
  if (/[.!?;]/.test(core)) return "plain"
  return core.split(/\s+/).filter(Boolean).length <= TERM_MAX_WORDS ? "define" : "plain"
}

export const BAR_HEIGHT = 44
export const BAR_HALF_WIDTH = 160
const GAP = 8
const EDGE = 8

export interface Box {
  top: number
  bottom: number
  left: number
  right: number
}

export interface Placement {
  top: number
  left: number
  /** "above": `top` is the bar's bottom edge; "below": its top edge. */
  side: "above" | "below"
}

/**
 * Above the selection when there is room inside the visible reader, otherwise
 * below it; null once the selection has scrolled out of the reader entirely.
 */
export function placeBar(
  selection: Box,
  view: Box,
  viewport: { width: number; height: number },
): Placement | null {
  if (selection.bottom < view.top || selection.top > view.bottom) return null

  const left = Math.max(
    BAR_HALF_WIDTH,
    Math.min((selection.left + selection.right) / 2, viewport.width - BAR_HALF_WIDTH),
  )
  const ceiling = Math.max(EDGE, view.top)
  if (selection.top - GAP - BAR_HEIGHT >= ceiling) {
    return { top: selection.top - GAP, left, side: "above" }
  }
  const floor = Math.min(viewport.height, view.bottom) - BAR_HEIGHT - EDGE
  // A selection taller than the view keeps the bar pinned inside it.
  return { top: Math.max(ceiling, Math.min(selection.bottom + GAP, floor)), left, side: "below" }
}
