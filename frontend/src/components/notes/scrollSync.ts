/**
 * Line-anchored scroll mapping between the markdown source pane and its preview.
 *
 * A single global ratio (scrollTop / scrollMax) cannot track these two panes: the
 * editor is monospace with one row per source line, while the preview is serif
 * prose whose block heights vary with headings, list spacing, images and KaTeX.
 * The pixels-per-source-line ratio therefore differs by region, and one constant
 * is only correct at the very top and the very bottom.
 *
 * Instead both panes are described as anchors — (source line, pixel offset) pairs
 * — and a position in one pane is converted by interpolating between the anchors
 * that bracket it. Because every offset is measured rather than derived from a
 * ratio, the mapping holds at any browser zoom level.
 */

export interface SourceAnchor {
  /** 1-based markdown line the block starts at. */
  line: number
  /** Pixel offset of the block from the pane's scroll origin. */
  top: number
}

interface Point {
  x: number
  y: number
}

/**
 * Piecewise-linear interpolation over points sorted ascending by x.
 * Clamps to the first/last point outside the covered range.
 */
export function interpolate(x: number, points: Point[]): number {
  if (points.length === 0) return 0
  const first = points[0]
  const last = points[points.length - 1]
  if (x <= first.x) return first.y
  if (x >= last.x) return last.y

  let lo = 0
  let hi = points.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (points[mid].x <= x) lo = mid
    else hi = mid
  }
  const a = points[lo]
  const b = points[hi]
  const span = b.x - a.x
  if (span <= 0) return a.y
  return a.y + ((x - a.x) / span) * (b.y - a.y)
}

/**
 * Anchors are read from the DOM in document order, but a block whose line is not
 * greater than its predecessor's (raw HTML, a plugin that rewrites positions)
 * would break the monotonic invariant interpolation depends on. Such blocks are
 * dropped rather than allowed to invert the mapping.
 *
 * The synthetic endpoints make the range total: line 1 sits at offset 0, and one
 * past the last line sits at the end of the scrollable content, so a position
 * before the first block or after the last still maps somewhere sensible.
 */
export function normalizeAnchors(
  raw: SourceAnchor[],
  totalLines: number,
  contentEnd: number,
): SourceAnchor[] {
  const anchors: SourceAnchor[] = []
  for (const anchor of raw) {
    if (!Number.isFinite(anchor.line) || !Number.isFinite(anchor.top)) continue
    const prev = anchors[anchors.length - 1]
    if (prev && (anchor.line <= prev.line || anchor.top < prev.top)) continue
    anchors.push(anchor)
  }

  if (anchors.length === 0) return []
  if (anchors[0].line > 1) anchors.unshift({ line: 1, top: 0 })

  const last = anchors[anchors.length - 1]
  const endLine = Math.max(totalLines + 1, last.line + 1)
  if (contentEnd > last.top) anchors.push({ line: endLine, top: contentEnd })
  return anchors
}

/** Scroll offset showing `line` (fractional) at the top of the pane. */
export function lineToOffset(line: number, anchors: SourceAnchor[]): number {
  return interpolate(
    line,
    anchors.map((a) => ({ x: a.line, y: a.top })),
  )
}

/** The (fractional) source line sitting at scroll offset `offset`. */
export function offsetToLine(offset: number, anchors: SourceAnchor[]): number {
  return interpolate(
    offset,
    anchors.map((a) => ({ x: a.top, y: a.line })),
  )
}
