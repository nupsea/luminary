/**
 * PDF highlight overlay utilities.
 *
 * Renders highlights as absolutely-positioned divs in a dedicated overlay
 * container rather than injecting <mark> elements into the pdfjs text layer.
 * This preserves pdfjs font metrics and eliminates text doubling/overlap.
 */

/** A rectangle relative to the overlay container. */
export interface OverlayRect {
  left: number
  top: number
  width: number
  height: number
}

/**
 * Compute bounding rects for a text range within the text layer spans.
 *
 * Uses the browser Range API to measure character positions without modifying
 * span content. The returned rects are relative to `containerRect` (the
 * overlay container's bounding box).
 *
 * @param spans - text layer <span> elements in order
 * @param parts - mapping of each span to its start/end offset in the
 *                concatenated full text (with single-space separators)
 * @param matchStart - start offset in the concatenated text
 * @param matchEnd - end offset in the concatenated text
 * @param containerRect - bounding rect of the overlay container
 */
export function computeHighlightRects(
  spans: HTMLSpanElement[],
  parts: { span: HTMLSpanElement; start: number; end: number }[],
  matchStart: number,
  matchEnd: number,
  containerRect: DOMRect,
): OverlayRect[] {
  const rects: OverlayRect[] = []
  const range = document.createRange()

  for (const part of parts) {
    if (part.end <= matchStart || part.start >= matchEnd) continue

    const spanText = part.span.textContent ?? ""
    const localStart = Math.max(0, matchStart - part.start)
    const localEnd = Math.min(spanText.length, matchEnd - part.start)

    // Find the text node inside the span
    const textNode = findTextNode(part.span)
    if (!textNode || !textNode.textContent) continue

    try {
      range.setStart(textNode, Math.min(localStart, textNode.textContent.length))
      range.setEnd(textNode, Math.min(localEnd, textNode.textContent.length))
    } catch {
      // Offset out of bounds -- skip this span
      continue
    }

    const clientRects = range.getClientRects()
    for (let i = 0; i < clientRects.length; i++) {
      const cr = clientRects[i]
      if (cr.width <= 0 || cr.height <= 0) continue
      rects.push({
        left: cr.left - containerRect.left,
        top: cr.top - containerRect.top,
        width: cr.width,
        height: cr.height,
      })
    }
  }

  range.detach()
  return mergeAdjacentRects(rects)
}

/**
 * Find the first Text node child of an element.
 * pdfjs text layer spans normally contain a single text node.
 */
function findTextNode(el: HTMLElement): Text | null {
  for (let i = 0; i < el.childNodes.length; i++) {
    if (el.childNodes[i].nodeType === Node.TEXT_NODE) {
      return el.childNodes[i] as Text
    }
  }
  return null
}

/**
 * Merge rects that are on the same line (similar top/height) and adjacent
 * or overlapping horizontally. Reduces DOM element count.
 */
function mergeAdjacentRects(rects: OverlayRect[]): OverlayRect[] {
  if (rects.length <= 1) return rects

  // Sort by top then left
  const sorted = [...rects].sort((a, b) => a.top - b.top || a.left - b.left)
  const merged: OverlayRect[] = [sorted[0]]

  for (let i = 1; i < sorted.length; i++) {
    const prev = merged[merged.length - 1]
    const curr = sorted[i]

    // Same line: tops within 2px and heights within 2px
    const sameLine = Math.abs(curr.top - prev.top) < 2 && Math.abs(curr.height - prev.height) < 2
    // Adjacent or overlapping: current left is within 2px of previous right edge
    const adjacent = sameLine && curr.left <= prev.left + prev.width + 2

    if (adjacent) {
      const newRight = Math.max(prev.left + prev.width, curr.left + curr.width)
      prev.width = newRight - prev.left
      prev.height = Math.max(prev.height, curr.height)
    } else {
      merged.push(curr)
    }
  }

  return merged
}

/**
 * Render overlay divs into the container for a set of rects.
 *
 * @param container - the highlight overlay div
 * @param rects - bounding rects relative to the container
 * @param color - CSS background color
 * @param dataAttr - data attribute name for identification (e.g. "data-pdf-highlight")
 * @param annotationId - optional annotation ID stored on the div for click handling
 * @param isActive - if true, gives the div a distinct active class
 */
export function renderOverlayDivs(
  container: HTMLDivElement,
  rects: OverlayRect[],
  color: string,
  dataAttr: string,
  annotationId?: string,
  isActive?: boolean,
): void {
  for (const rect of rects) {
    const div = document.createElement("div")
    div.setAttribute(dataAttr, "1")
    div.style.position = "absolute"
    div.style.left = `${rect.left}px`
    div.style.top = `${rect.top}px`
    div.style.width = `${rect.width}px`
    div.style.height = `${rect.height}px`
    div.style.backgroundColor = color
    div.style.borderRadius = "2px"
    div.style.pointerEvents = annotationId ? "auto" : "none"
    div.style.cursor = annotationId ? "pointer" : "default"
    div.style.mixBlendMode = "multiply"
    if (annotationId) div.setAttribute("data-annotation-id", annotationId)
    if (isActive) div.setAttribute("data-active-search-match", "1")
    container.appendChild(div)
  }
}

/**
 * Remove overlay divs from the container.
 * If dataAttr is provided, only remove divs with that attribute.
 * Otherwise remove all children.
 */
export function clearOverlays(container: HTMLDivElement, dataAttr?: string): void {
  if (!dataAttr) {
    container.replaceChildren()
    return
  }
  container.querySelectorAll(`[${dataAttr}]`).forEach((el) => el.remove())
}
