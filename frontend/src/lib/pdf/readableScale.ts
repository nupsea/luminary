// What a page should be zoomed to in order to be *read*.
//
// Fit-to-width answers a geometric question -- how big can the page be without a
// horizontal scrollbar -- and that answer has nothing to do with legibility. The
// same book PDF fitted to a narrow pane rendered its 10.5pt body type at 1.18
// (12 CSS px, reported as too small to read) and, once the pane was widened,
// at 2.9 (30 CSS px, reported as too big). Neither number was wrong about the
// width; both were wrong about the type.
//
// So the target is the type itself: measure the body text the page actually
// carries and scale it to a comfortable size, with fit-width left as the ceiling
// it may never cross.

/** Body text lands here, in CSS pixels. */
export const TARGET_BODY_PX = 17

/**
 * The zoom never goes below this to satisfy the target.
 *
 * The two cases that bracket it: a slide deck set in 30pt would ask for 0.57,
 * shrinking a page that already fits into a corner of the pane, so the floor
 * holds it at 1.0; an A0 poster whose fit-width is 0.2 must still fit, so
 * fit-width is applied last and wins over the floor.
 */
export const MIN_READABLE_SCALE = 1.0

/** One drawn run of text, as pdf.js reports it: height is in PDF units. */
export interface TextExtent {
  str: string
  height: number
}

/**
 * The height of the page's *body* type, in PDF units.
 *
 * Weighted by character count, because that is what separates body text from
 * everything else on the page: a running head, a folio and a chapter title are
 * each a handful of characters, and the paragraphs are thousands. A plain median
 * over runs would let a page of short lines be decided by its heading.
 *
 * Returns null for a page with no text at all -- a scan, a full-page figure --
 * where there is nothing to size against and fit-width is the only answer.
 */
export function bodyTextHeight(items: readonly TextExtent[]): number | null {
  const weighted = items
    .map((item) => ({ height: item.height, weight: item.str.trim().length }))
    .filter((item) => item.height > 0 && item.weight > 0)
    .sort((a, b) => a.height - b.height)
  const total = weighted.reduce((sum, item) => sum + item.weight, 0)
  if (total === 0) return null
  let seen = 0
  for (const item of weighted) {
    seen += item.weight
    if (seen * 2 >= total) return item.height
  }
  return null
}

/**
 * The scale to render at: body type at {@link TARGET_BODY_PX}, floored so a
 * large-type page is not shrunk, and capped at fit-width so nothing the reader
 * has to scroll sideways to finish a line ever ships.
 */
export function readableScale({
  bodyHeight,
  fitWidthScale,
  targetPx = TARGET_BODY_PX,
}: {
  bodyHeight: number | null
  fitWidthScale: number
  targetPx?: number
}): number {
  if (bodyHeight === null || bodyHeight <= 0) return fitWidthScale
  return Math.min(fitWidthScale, Math.max(MIN_READABLE_SCALE, targetPx / bodyHeight))
}
