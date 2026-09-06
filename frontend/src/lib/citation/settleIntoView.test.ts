import { describe, expect, it } from "vitest"

import { SETTLE_MAX_TICKS, settleIntoView } from "./settleIntoView"

/** A scheduler that runs queued work on demand, one tick at a time. */
function fakeClock() {
  const queue = new Map<number, () => void>()
  let next = 1
  return {
    schedule: (fn: () => void) => {
      queue.set(next, fn)
      return next++
    },
    cancel: (handle: number) => void queue.delete(handle),
    /** Run every callback currently queued. */
    tick: () => {
      const due = [...queue.entries()]
      queue.clear()
      due.forEach(([, fn]) => fn())
      return due.length
    },
    pending: () => queue.size,
  }
}

/** A mark whose distance from centre follows a script, plus a centring count. */
function scriptedMark(distances: (number | null)[]) {
  let step = 0
  const state = { centred: 0 }
  const current = () => distances[Math.min(step, distances.length - 1)]
  return {
    state,
    deps: {
      find: () => {
        if (current() !== null) return "mark"
        step += 1
        return null
      },
      distance: () => {
        const value = current()
        step += 1
        return value ?? 0
      },
      centre: () => void (state.centred += 1),
    },
  }
}

describe("settleIntoView", () => {
  it("stops once the mark has been at rest twice running", () => {
    const clock = fakeClock()
    const mark = scriptedMark([600, 40, 2, 1])
    settleIntoView({ ...mark.deps, schedule: clock.schedule, cancel: clock.cancel })
    for (let i = 0; i < 6; i++) clock.tick()
    expect(mark.state.centred).toBe(2)
    expect(clock.pending()).toBe(0)
  })

  it("re-centres when the mark drifts after arriving", () => {
    // A section mounting above the passage pushes it back down; the whole point
    // of the loop is that this is corrected rather than left to the reader.
    const clock = fakeClock()
    const mark = scriptedMark([600, 4, 900, 3, 1])
    settleIntoView({ ...mark.deps, schedule: clock.schedule, cancel: clock.cancel })
    for (let i = 0; i < 6; i++) clock.tick()
    expect(mark.state.centred).toBe(2)
  })

  it("gives up on a passage that cannot reach the centre", () => {
    // The last paragraph of a document: nothing left to scroll, so the distance
    // never improves and the scroller must be handed back to the reader.
    const clock = fakeClock()
    const mark = scriptedMark([300])
    settleIntoView({ ...mark.deps, schedule: clock.schedule, cancel: clock.cancel })
    for (let i = 0; i < 10; i++) clock.tick()
    expect(mark.state.centred).toBe(1)
    expect(clock.pending()).toBe(0)
  })

  it("waits for a mark that has yet to render, but not forever", () => {
    const clock = fakeClock()
    const mark = scriptedMark([null])
    settleIntoView({ ...mark.deps, schedule: clock.schedule, cancel: clock.cancel })
    let ran = 0
    for (let i = 0; i < SETTLE_MAX_TICKS + 5; i++) ran += clock.tick()
    expect(ran).toBe(SETTLE_MAX_TICKS)
    expect(mark.state.centred).toBe(0)
  })

  it("centres a mark that renders late", () => {
    const clock = fakeClock()
    const mark = scriptedMark([null, null, 500, 3, 1])
    settleIntoView({ ...mark.deps, schedule: clock.schedule, cancel: clock.cancel })
    for (let i = 0; i < 8; i++) clock.tick()
    expect(mark.state.centred).toBe(1)
  })

  it("cancels cleanly when the reader leaves", () => {
    const clock = fakeClock()
    const mark = scriptedMark([600, 600, 600])
    const stop = settleIntoView({ ...mark.deps, schedule: clock.schedule, cancel: clock.cancel })
    stop()
    expect(clock.pending()).toBe(0)
    expect(mark.state.centred).toBe(0)
  })
})
