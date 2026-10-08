/**
 * Page turning at the edges of the single-page PDF view: scrolling or pressing
 * down past the bottom of a page continues onto the next one, and up past the
 * top returns to the previous one, landing at its bottom.
 */

import { useEffect, useRef } from "react"

export type Landing = "top" | "bottom"

interface ScrollMetrics {
  scrollTop: number
  clientHeight: number
  scrollHeight: number
}

/** Sub-pixel layout leaves scrollTop a fraction short of the true end. */
const EDGE_SLACK = 2

export function atEdge(m: ScrollMetrics, direction: 1 | -1): boolean {
  return direction > 0
    ? m.scrollTop + m.clientHeight >= m.scrollHeight - EDGE_SLACK
    : m.scrollTop <= EDGE_SLACK
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
 * One wheel gesture turns at most one page. The push past the edge must build
 * past a mouse notch (100-120px) before a page turns, so brushing the edge on a
 * trackpad does nothing; after a turn, the gesture's momentum is swallowed until
 * the wheel goes quiet.
 */
const PUSH_THRESHOLD = 100
const QUIET_MS = 180
const MAX_HOLD_MS = 1200

export function createWheelPager() {
  let push = 0
  let turnedAt = -Infinity
  let holdUntil = -Infinity

  return (m: ScrollMetrics, deltaY: number, now: number): -1 | 0 | 1 => {
    if (now < holdUntil) {
      holdUntil = Math.min(turnedAt + MAX_HOLD_MS, now + QUIET_MS)
      return 0
    }
    if (deltaY === 0) return 0
    const direction = deltaY > 0 ? 1 : -1
    if (!atEdge(m, direction)) {
      push = 0
      return 0
    }
    if (Math.sign(push) === -direction) push = 0
    push += deltaY
    if (Math.abs(push) < PUSH_THRESHOLD) return 0
    push = 0
    turnedAt = now
    holdUntil = now + QUIET_MS
    return direction
  }
}

const WHEEL_LINE_PX = 40

function isInteractive(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || Boolean(target.closest("input, textarea, select, button, a, [role='textbox']"))
}

/**
 * Wires wheel and keyboard edge-paging onto the scroll area. Returns where the
 * next page should land, which the renderer applies once the page has its size.
 */
export function usePdfEdgePaging(
  scrollAreaRef: React.RefObject<HTMLDivElement | null>,
  currentPage: number,
  totalPages: number,
  goToPage: (n: number) => void,
  /** The scroll area exists only once the document has loaded. */
  ready: boolean,
): React.RefObject<Landing> {
  const landingRef = useRef<Landing>("top")
  const stateRef = useRef({ currentPage, totalPages, goToPage })
  useEffect(() => {
    stateRef.current = { currentPage, totalPages, goToPage }
  }, [currentPage, totalPages, goToPage])

  useEffect(() => {
    const el = scrollAreaRef.current
    if (!el || !ready) return
    const pager = createWheelPager()

    function turn(direction: 1 | -1): boolean {
      const { currentPage: page, totalPages: total, goToPage: go } = stateRef.current
      const target = page + direction
      if (target < 1 || target > total) return false
      landingRef.current = direction > 0 ? "top" : "bottom"
      go(target)
      return true
    }

    function handleWheel(e: WheelEvent) {
      if (e.ctrlKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return // pinch-zoom, sideways pan
      const deltaY = e.deltaMode === WheelEvent.DOM_DELTA_LINE ? e.deltaY * WHEEL_LINE_PX : e.deltaY
      const direction = pager(el!, deltaY, e.timeStamp)
      if (direction !== 0) turn(direction)
    }

    function handleKeyDown(e: KeyboardEvent) {
      if (e.defaultPrevented || e.altKey || e.metaKey || e.ctrlKey || isInteractive(e.target)) return
      // Mounted but hidden behind another reader tab.
      if (el!.offsetParent === null) return
      const step = keyStep(e.key, e.shiftKey, el!.clientHeight)
      if (step === null) return
      e.preventDefault()
      const direction = step > 0 ? 1 : -1
      if (atEdge(el!, direction)) turn(direction)
      else el!.scrollBy({ top: step, behavior: e.repeat ? "auto" : "smooth" })
    }

    el.addEventListener("wheel", handleWheel, { passive: true })
    window.addEventListener("keydown", handleKeyDown)
    return () => {
      el.removeEventListener("wheel", handleWheel)
      window.removeEventListener("keydown", handleKeyDown)
    }
  }, [scrollAreaRef, ready])

  return landingRef
}
