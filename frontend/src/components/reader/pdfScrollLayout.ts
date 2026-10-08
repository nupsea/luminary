/**
 * Layout of the continuous PDF view: every page stacked in one scroll, so a
 * selection, the wheel and the paging keys all run across page breaks. Only the
 * pages near the viewport hold a canvas and text layer.
 */

import { useEffect } from "react"

/** Space above the first page and below the last. */
export const PAGE_PAD = 16
export const PAGE_GAP = 16

export interface PageLayout {
  /** Offset of each page's top edge inside the scroll content. */
  tops: number[]
  heights: number[]
  totalHeight: number
}

export function layoutPages(heights: number[]): PageLayout {
  const tops: number[] = []
  let y = PAGE_PAD
  for (const h of heights) {
    tops.push(y)
    y += h + PAGE_GAP
  }
  return { tops, heights, totalHeight: heights.length ? y - PAGE_GAP + PAGE_PAD : 0 }
}

/** Index of the first page whose bottom edge is below `y`. */
function firstEndingAfter(layout: PageLayout, y: number): number {
  let lo = 0
  let hi = layout.tops.length - 1
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (layout.tops[mid] + layout.heights[mid] > y) hi = mid
    else lo = mid + 1
  }
  return lo
}

interface Viewport {
  scrollTop: number
  clientHeight: number
  scrollHeight: number
}

/** Sub-pixel layout leaves scrollTop a fraction short of the true end. */
const EDGE_SLACK = 2

/** The 1-based page that fills most of the viewport; the last page once scrolled to the end. */
export function pageInView(layout: PageLayout, v: Viewport): number {
  const count = layout.tops.length
  if (count === 0) return 1
  if (v.scrollTop + v.clientHeight >= v.scrollHeight - EDGE_SLACK) return count
  const bottom = v.scrollTop + v.clientHeight
  let best = firstEndingAfter(layout, v.scrollTop)
  let bestShown = -1
  for (let i = best; i < count && layout.tops[i] < bottom; i++) {
    const top = layout.tops[i]
    const shown = Math.min(bottom, top + layout.heights[i]) - Math.max(v.scrollTop, top)
    if (shown > bestShown) {
      best = i
      bestShown = shown
    }
  }
  return best + 1
}

/** 1-based inclusive range of pages within one viewport of the visible area: these get rendered. */
export function pagesNear(layout: PageLayout, scrollTop: number, clientHeight: number): [number, number] {
  const count = layout.tops.length
  if (count === 0) return [1, 0]
  const first = firstEndingAfter(layout, scrollTop - clientHeight)
  const bottom = scrollTop + 2 * clientHeight
  let last = first
  while (last + 1 < count && layout.tops[last + 1] < bottom) last++
  return [first + 1, last + 1]
}

/** Where the viewport's top edge sits, as a page and a fraction of it, so a zoom keeps the place. */
export interface ScrollAnchor {
  page: number
  fraction: number
}

export function anchorAt(layout: PageLayout, scrollTop: number): ScrollAnchor {
  if (layout.tops.length === 0) return { page: 1, fraction: 0 }
  const i = firstEndingAfter(layout, scrollTop)
  return { page: i + 1, fraction: (scrollTop - layout.tops[i]) / layout.heights[i] }
}

export function scrollTopFor(layout: PageLayout, anchor: ScrollAnchor): number {
  const i = Math.min(anchor.page, layout.tops.length) - 1
  if (i < 0) return 0
  return Math.max(0, layout.tops[i] + anchor.fraction * layout.heights[i])
}

const LINE_STEP = 60
/** A page step keeps one line of overlap, as browsers do, so the reader keeps their place. */
const PAGE_OVERLAP = 0.9

/** Signed scroll distance for a paging key, or null for any other key. */
export function keyStep(key: string, shiftKey: boolean, clientHeight: number): number | null {
  const page = Math.round(clientHeight * PAGE_OVERLAP)
  switch (key) {
    case "ArrowDown": return shiftKey ? null : LINE_STEP
    case "ArrowUp": return shiftKey ? null : -LINE_STEP
    case "PageDown": return page
    case "PageUp": return -page
    case " ": return shiftKey ? -page : page
    default: return null
  }
}

/**
 * Whether the focused control uses this key itself. Ignoring every button would
 * leave the arrows dead right after the PDF tab is clicked, since focus stays on the tab.
 */
function focusOwnsKey(target: EventTarget | null, key: string): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable || target.closest("input, textarea, select, [role='textbox']")) return true
  if (key === " ") return Boolean(target.closest("button, a, [role='button']"))
  return Boolean(target.closest("[role='tablist'], [role='menu'], [role='listbox'], [role='radiogroup'], [role='slider']"))
}

/**
 * The paging keys scroll the PDF wherever focus is. A browser scrolls only the
 * focused scroller, and clicking a page's text layer does not focus it.
 */
export function usePdfKeyScroll(
  scrollAreaRef: React.RefObject<HTMLDivElement | null>,
  /** The scroll area exists only once the document has loaded. */
  ready: boolean,
): void {
  useEffect(() => {
    const el = scrollAreaRef.current
    if (!el || !ready) return
    function handleKeyDown(e: KeyboardEvent) {
      if (e.defaultPrevented || e.altKey || e.metaKey || e.ctrlKey || focusOwnsKey(e.target, e.key)) return
      // Mounted but hidden behind another reader tab.
      if (el!.offsetParent === null) return
      const step = keyStep(e.key, e.shiftKey, el!.clientHeight)
      if (step === null) return
      e.preventDefault()
      el!.scrollBy({ top: step, behavior: e.repeat ? "auto" : "smooth" })
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [scrollAreaRef, ready])
}
