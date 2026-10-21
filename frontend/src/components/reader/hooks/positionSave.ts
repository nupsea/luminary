// A section counts as the reading position once the reader has stayed on it this long.
export const POSITION_SETTLE_MS = 10_000

/**
 * Saves the latest value once it has held for `settleMs`, and never the same value twice running.
 *
 * Fed by the Read view's current section. An observer attached when the document loaded
 * found no section elements (they arrive with a second query), never ran again, and so
 * saved no position: no resume offer, and chapter backfill (#231) never saw a book being read.
 */
export function settledSaver<T>(save: (value: T) => void, settleMs = POSITION_SETTLE_MS) {
  let saved: T | undefined
  let timer: ReturnType<typeof setTimeout> | undefined

  function stop() {
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
  }

  return {
    reach(value: T) {
      stop()
      if (value === saved) return
      timer = setTimeout(() => {
        timer = undefined
        saved = value
        save(value)
      }, settleMs)
    },
    stop,
  }
}
