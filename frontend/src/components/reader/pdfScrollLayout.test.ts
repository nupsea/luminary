import { describe, expect, it } from "vitest"
import { PAGE_GAP, PAGE_PAD, anchorAt, keyStep, layoutPages, pageInView, pagesNear, scrollTopFor } from "./pdfScrollLayout"

// Ten 1000px pages: page n (1-based) starts at 16 + (n - 1) * 1016.
const layout = layoutPages(Array(10).fill(1000))
const top = (n: number) => layout.tops[n - 1]
const view = (scrollTop: number, clientHeight = 600) => ({
  scrollTop,
  clientHeight,
  scrollHeight: layout.totalHeight,
})

describe("layoutPages", () => {
  it("stacks pages with a gap between them and padding at both ends", () => {
    expect(top(1)).toBe(PAGE_PAD)
    expect(top(2)).toBe(PAGE_PAD + 1000 + PAGE_GAP)
    expect(layout.totalHeight).toBe(top(10) + 1000 + PAGE_PAD)
    expect(layoutPages([]).totalHeight).toBe(0)
  })
})

describe("pageInView", () => {
  it("names the page that fills most of the viewport", () => {
    expect(pageInView(layout, view(0))).toBe(1)
    // the break sits a third of the way down: page 2 fills the rest
    expect(pageInView(layout, view(top(2) - 200))).toBe(2)
    // the break sits two thirds of the way down: still page 1
    expect(pageInView(layout, view(top(2) - 400))).toBe(1)
  })

  it("names the last page once scrolled to the end", () => {
    const short = layoutPages([1000, 1000, 200])
    const end = { scrollTop: short.totalHeight - 600, clientHeight: 600, scrollHeight: short.totalHeight }
    expect(pageInView(short, end)).toBe(3)
  })
})

describe("pagesNear", () => {
  it("covers the visible pages plus a viewport either side", () => {
    expect(pagesNear(layout, 0, 600)).toEqual([1, 2])
    expect(pagesNear(layout, top(5), 600)).toEqual([4, 6])
    expect(pagesNear(layout, layout.totalHeight - 600, 600)).toEqual([9, 10])
  })
})

describe("scroll anchor", () => {
  it("keeps the same place on the page when the zoom changes", () => {
    const anchor = anchorAt(layout, top(4) + 250)
    expect(anchor).toEqual({ page: 4, fraction: 0.25 })
    const zoomed = layoutPages(Array(10).fill(2000))
    expect(scrollTopFor(zoomed, anchor)).toBe(zoomed.tops[3] + 500)
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
