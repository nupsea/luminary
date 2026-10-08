import { describe, expect, it } from "vitest"
import { atEdge, createWheelPager, keyStep } from "./pdfEdgePaging"

const middle = { scrollTop: 300, clientHeight: 600, scrollHeight: 1600 }
const bottom = { scrollTop: 1000, clientHeight: 600, scrollHeight: 1600 }
const top = { scrollTop: 0, clientHeight: 600, scrollHeight: 1600 }
// fit-to-page: the whole page is visible, so it is at both edges at once
const fits = { scrollTop: 0, clientHeight: 900, scrollHeight: 900 }

describe("atEdge", () => {
  it("tells the bottom and top edges apart from the middle", () => {
    expect(atEdge(bottom, 1)).toBe(true)
    expect(atEdge(middle, 1)).toBe(false)
    expect(atEdge(top, -1)).toBe(true)
    expect(atEdge(middle, -1)).toBe(false)
    expect(atEdge({ ...bottom, scrollTop: 999.4 }, 1)).toBe(true)
  })
})

describe("keyStep", () => {
  it("maps paging keys and leaves Shift+arrows to text selection", () => {
    expect(keyStep("ArrowDown", false, 600)).toBe(60)
    expect(keyStep("ArrowUp", false, 600)).toBe(-60)
    expect(keyStep("ArrowDown", true, 600)).toBeNull()
    expect(keyStep("PageDown", false, 600)).toBe(540)
    expect(keyStep(" ", true, 600)).toBe(-540)
    expect(keyStep("ArrowRight", false, 600)).toBeNull()
  })
})

describe("createWheelPager", () => {
  it("scrolls within the page without turning it", () => {
    const pager = createWheelPager()
    expect(pager(middle, 400, 0)).toBe(0)
  })

  it("turns a page once the push past the edge builds up", () => {
    const pager = createWheelPager()
    expect(pager(bottom, 40, 0)).toBe(0)
    expect(pager(bottom, 40, 16)).toBe(0)
    expect(pager(bottom, 40, 32)).toBe(1)
    const back = createWheelPager()
    expect(back(top, -120, 0)).toBe(-1)
  })

  it("forgets a push that was interrupted by scrolling inside the page", () => {
    const pager = createWheelPager()
    expect(pager(bottom, 80, 0)).toBe(0)
    expect(pager(middle, -10, 16)).toBe(0)
    expect(pager(bottom, 80, 32)).toBe(0)
  })

  it("turns one page per gesture, not one per momentum event", () => {
    const pager = createWheelPager()
    expect(pager(fits, 120, 0)).toBe(1)
    let turns = 0
    for (let t = 16; t < 1000; t += 16) turns += Math.abs(pager(fits, 120, t))
    expect(turns).toBe(0)
    // a fresh gesture after the wheel has gone quiet turns again
    expect(pager(fits, 120, 1400)).toBe(1)
  })

  it("cannot be held off forever by a continuous wheel", () => {
    const pager = createWheelPager()
    expect(pager(fits, 120, 0)).toBe(1)
    let turned = 0
    for (let t = 16; t < 3000 && !turned; t += 16) turned = pager(fits, 120, t)
    expect(turned).toBe(1)
  })
})
