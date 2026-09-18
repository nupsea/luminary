import { describe, expect, it } from "vitest"

import { isOreillyUrl, parseOreillyChapter } from "./oreillyApi"

describe("isOreillyUrl", () => {
  it("matches O'Reilly book URLs and URNs", () => {
    expect(isOreillyUrl("https://learning.oreilly.com/library/view/ddia/9781491903063/")).toBe(true)
    expect(isOreillyUrl("https://www.oreilly.com/library/view/fluent-python/9781492056348/")).toBe(true)
    expect(isOreillyUrl("urn:orm:book:9781491903063")).toBe(true)
  })

  it("does not claim a URL that only mentions O'Reilly", () => {
    expect(isOreillyUrl("https://example.com/review?via=learning.oreilly.com")).toBe(false)
    expect(isOreillyUrl("https://www.oreilly.com/radar/some-article/")).toBe(false)
    expect(isOreillyUrl("")).toBe(false)
  })
})

describe("parseOreillyChapter", () => {
  it("returns the chapter file of a deep link", () => {
    expect(parseOreillyChapter("https://learning.oreilly.com/library/view/x/9798341621701/ch06.html#ch06")).toBe("ch06.html")
    expect(parseOreillyChapter("https://learning.oreilly.com/library/view/x/9798341621701/")).toBeNull()
  })
})
