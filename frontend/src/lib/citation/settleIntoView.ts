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

export const SCROLL_KEYS = new Set([
  "ArrowUp",
  "ArrowDown",
  "PageUp",
  "PageDown",
  "Home",
  "End",
  " ",
  "Spacebar",
])

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
  /**
   * Event target to listen for user interactions that should cancel the loop.
   * If not provided, defaults to `window` if running in a browser environment.
   * Pass `null` explicitly to disable interaction listeners.
   */
  userEventsTarget?: EventTarget | null
}

/**
 * Centre the mark and keep it centred until it settles. Returns a cancel
 * function; calling it stops the loop.
 *
 * Exits when:
 * 1. Arrived: the mark is within tolerance twice running.
 * 2. Stuck: the distance stops improving (e.g. end of document).
 * 3. User interaction: the user scrolls or interacts, immediately handing control back.
 * 4. Bound: maxTicks elapsed.
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
  userEventsTarget,
}: SettleDeps<T>): () => void {
  let handle: number | null = null
  let ticks = 0
  let arrived = 0
  let stalled = 0
  let previous: number | null = null
  let cleanupListeners: (() => void) | null = null

  const stop = () => {
    if (handle !== null) {
      cancel(handle)
      handle = null
    }
    if (cleanupListeners) {
      cleanupListeners()
      cleanupListeners = null
    }
  }

  const eventTarget =
    userEventsTarget !== undefined
      ? userEventsTarget
      : typeof window !== "undefined"
      ? window
      : null

  if (eventTarget && typeof eventTarget.addEventListener === "function") {
    const onUserAction = () => {
      stop()
    }
    const onKeyDown = (e: Event) => {
      const key = "key" in e ? (e as { key: string }).key : undefined
      if (key && SCROLL_KEYS.has(key)) {
        stop()
      }
    }
    eventTarget.addEventListener("wheel", onUserAction, { passive: true, capture: true })
    eventTarget.addEventListener("touchmove", onUserAction, { passive: true, capture: true })
    eventTarget.addEventListener("pointerdown", onUserAction, { passive: true, capture: true })
    eventTarget.addEventListener("keydown", onKeyDown, { passive: true, capture: true })

    cleanupListeners = () => {
      eventTarget.removeEventListener("wheel", onUserAction, { capture: true })
      eventTarget.removeEventListener("touchmove", onUserAction, { capture: true })
      eventTarget.removeEventListener("pointerdown", onUserAction, { capture: true })
      eventTarget.removeEventListener("keydown", onKeyDown, { capture: true })
    }
  }

  const tick = () => {
    handle = null
    const target = find()
    if (target) {
      const offset = Math.abs(distance(target))
      if (offset <= tolerancePx) {
        if (++arrived >= SETTLE_CONFIRM) {
          stop()
          return
        }
      } else if (previous !== null && Math.abs(previous - offset) <= tolerancePx) {
        if (++stalled >= SETTLE_CONFIRM) {
          stop()
          return
        }
      } else {
        arrived = 0
        stalled = 0
        centre(target)
      }
      previous = offset
    }
    if (++ticks < maxTicks) {
      handle = schedule(tick, intervalMs)
    } else {
      stop()
    }
  }

  handle = schedule(tick, intervalMs)
  return stop
}
