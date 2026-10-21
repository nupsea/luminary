import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { POSITION_SETTLE_MS, settledSaver } from "./positionSave"

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe("settledSaver", () => {
  it("saves a section once the reader has stayed on it", () => {
    const save = vi.fn()
    const saver = settledSaver(save)
    saver.reach("ch3")
    vi.advanceTimersByTime(POSITION_SETTLE_MS - 1)
    expect(save).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(save).toHaveBeenCalledWith("ch3")
  })

  it("saves only where the reader settled, not each section scrolled past", () => {
    const save = vi.fn()
    const saver = settledSaver(save)
    saver.reach("ch2")
    vi.advanceTimersByTime(3_000)
    saver.reach("ch3")
    vi.advanceTimersByTime(POSITION_SETTLE_MS)
    expect(save.mock.calls).toEqual([["ch3"]])
  })

  it("does not save the same section twice running", () => {
    const save = vi.fn()
    const saver = settledSaver(save)
    saver.reach("ch3")
    vi.advanceTimersByTime(POSITION_SETTLE_MS)
    saver.reach("ch3")
    vi.advanceTimersByTime(POSITION_SETTLE_MS)
    expect(save).toHaveBeenCalledTimes(1)
  })

  it("going back to the saved section drops the one passed on the way", () => {
    const save = vi.fn()
    const saver = settledSaver(save)
    saver.reach("ch3")
    vi.advanceTimersByTime(POSITION_SETTLE_MS)
    saver.reach("ch4")
    saver.reach("ch3")
    vi.advanceTimersByTime(POSITION_SETTLE_MS)
    expect(save.mock.calls).toEqual([["ch3"]])
  })

  it("saves nothing once stopped", () => {
    const save = vi.fn()
    const saver = settledSaver(save)
    saver.reach("ch3")
    saver.stop()
    vi.advanceTimersByTime(POSITION_SETTLE_MS)
    expect(save).not.toHaveBeenCalled()
  })
})
