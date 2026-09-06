// Keeping a citation on screen while the page around it is still moving.
//
// Scrolling to the mark once is not enough in a lazily rendered reader. Sections
// mount as they come into view, so the act of scrolling to a passage grows the
// document above it and carries it back off screen -- the reader arrives from a
// citation and has to hunt up or down for the highlight that was supposed to be
// waiting for them.
//
// So the target is not "scroll once" but "stay at rest": re-centre until the
// mark stops moving, then stop. All measurement and scheduling is injected, so
// the policy below is testable without a DOM.

/**
 * How often to check where the mark ended up.
 *
 * Short, because each check is one `getBoundingClientRect` and the loop is a
 * chase: sections mount as the reader passes them, so every correction is
 * followed by another shift, and a 150ms interval spent eight seconds walking
 * down a 23K-word book before the passage came to rest.
 */
export const SETTLE_INTERVAL_MS = 50

/** Within this many pixels of centre counts as arrived. */
export const SETTLE_TOLERANCE_PX = 24

/** Consecutive checks that must agree before the loop stops. */
export const SETTLE_CONFIRM = 2

/**
 * Upper bound on the whole loop, including waiting for the mark to render.
 *
 * Generous, because it is a backstop and not the policy: arrival and stall are
 * what normally end the loop, within a few hundred milliseconds. A 3s bound gave
 * up mid-chase on a 23K-word book, 3535px short of the passage, while sections
 * mounting above it were still moving it around.
 */
export const SETTLE_MAX_TICKS = 200

export interface SettleDeps<T> {
  /** The mark, or null while it has yet to render. */
  find: () => T | null
  /** Signed pixels between the mark and where it should come to rest. */
  distance: (target: T) => number
  /** Ask for it to be centred. */
  centre: (target: T) => void
  schedule: (fn: () => void, ms: number) => number
  cancel: (handle: number) => void
  intervalMs?: number
  tolerancePx?: number
  maxTicks?: number
}

/**
 * Centre the mark and keep it centred until it settles. Returns a cancel
 * function; calling it stops the loop.
 *
 * Two ways to stop other than the tick bound. Arrived: the mark is within
 * tolerance twice running. Stuck: the distance stops improving, which is what a
 * passage near the end of a document looks like -- it cannot reach the centre
 * because there is nothing left to scroll, and continuing to yank the scroller
 * every interval would fight the reader for control of the page.
 */
export function settleIntoView<T>({
  find,
  distance,
  centre,
  schedule,
  cancel,
  intervalMs = SETTLE_INTERVAL_MS,
  tolerancePx = SETTLE_TOLERANCE_PX,
  maxTicks = SETTLE_MAX_TICKS,
}: SettleDeps<T>): () => void {
  let handle: number | null = null
  let ticks = 0
  let arrived = 0
  let stalled = 0
  let previous: number | null = null

  const stop = () => {
    if (handle !== null) cancel(handle)
    handle = null
  }

  const tick = () => {
    handle = null
    const target = find()
    if (target) {
      const offset = Math.abs(distance(target))
      if (offset <= tolerancePx) {
        if (++arrived >= SETTLE_CONFIRM) return
      } else if (previous !== null && Math.abs(previous - offset) <= tolerancePx) {
        if (++stalled >= SETTLE_CONFIRM) return
      } else {
        arrived = 0
        stalled = 0
        centre(target)
      }
      previous = offset
    }
    if (++ticks < maxTicks) handle = schedule(tick, intervalMs)
  }

  handle = schedule(tick, intervalMs)
  return stop
}
