import { describe, expect, it } from "vitest"

import { MIN_READABLE_SCALE, TARGET_BODY_PX, bodyTextHeight, readableScale } from "./readableScale"

const body = (height: number, chars: number) => ({ height, str: "x".repeat(chars) })

describe("bodyTextHeight", () => {
  it("reports the type the page is mostly set in, not its largest", () => {
    // A chapter opening: one big title, then the prose.
    expect(bodyTextHeight([body(24, 30), body(10.5, 400), body(10.5, 600)])).toBe(10.5)
  })

  it("is not swayed by many short runs of furniture", () => {
    // Running head, folio and marginalia are numerous and tiny; the paragraph
    // still holds the majority of the characters.
    const items = [...Array(20)].map(() => body(7, 5))
    expect(bodyTextHeight([...items, body(11, 2000)])).toBe(11)
  })

  it("returns null for a page with no text", () => {
    expect(bodyTextHeight([])).toBeNull()
    expect(bodyTextHeight([body(0, 10), { height: 12, str: "   " }])).toBeNull()
  })
})

describe("readableScale", () => {
  it("puts body type at the target size when there is room", () => {
    expect(readableScale({ bodyHeight: 10, fitWidthScale: 2.9 })).toBeCloseTo(1.7)
  })

  it("never exceeds fit-width, which would mean scrolling sideways to read a line", () => {
    // The narrow-pane case: the target asks for 1.7 and only 1.18 fits.
    expect(readableScale({ bodyHeight: 10, fitWidthScale: 1.18 })).toBe(1.18)
  })

  it("does not shrink a page that is already set in large type", () => {
    // A 30pt slide would ask for 0.57.
    expect(readableScale({ bodyHeight: 30, fitWidthScale: 2 })).toBe(MIN_READABLE_SCALE)
  })

  it("lets fit-width win over the floor for an oversized page", () => {
    expect(readableScale({ bodyHeight: 30, fitWidthScale: 0.2 })).toBe(0.2)
  })

  it("falls back to fit-width when the page has no text to size against", () => {
    expect(readableScale({ bodyHeight: null, fitWidthScale: 2.9 })).toBe(2.9)
  })

  it("keeps the target as the only thing deciding the size", () => {
    expect(readableScale({ bodyHeight: TARGET_BODY_PX, fitWidthScale: 5 })).toBe(MIN_READABLE_SCALE)
  })
})
