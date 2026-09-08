import { describe, expect, it } from "vitest"

import { appendCapture } from "./noteCapture"

describe("appendCapture", () => {
  it("uses the capture when the draft is empty", () => {
    expect(appendCapture("", "> quoted")).toBe("> quoted")
    expect(appendCapture("   \n ", "> quoted")).toBe("> quoted")
  })

  it("leaves the draft alone when the capture is empty", () => {
    expect(appendCapture("written by hand", "")).toBe("written by hand")
    expect(appendCapture("written by hand", "  ")).toBe("written by hand")
  })

  it("separates the capture from the draft by one blank line", () => {
    expect(appendCapture("first", "> second")).toBe("first\n\n> second")
  })

  it("does not stack blank lines onto a draft that ends in them", () => {
    expect(appendCapture("first\n\n", "> second")).toBe("first\n\n> second")
  })
})
