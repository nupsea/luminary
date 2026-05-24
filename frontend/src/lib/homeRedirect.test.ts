import { describe, expect, it } from "vitest"
import { getHomeRedirectTarget } from "./homeRedirect"

describe("getHomeRedirectTarget", () => {
  it("returns null when there is no search string", () => {
    expect(getHomeRedirectTarget("")).toBeNull()
  })

  it("returns null when no legacy params are present", () => {
    expect(getHomeRedirectTarget("?foo=bar")).toBeNull()
    expect(getHomeRedirectTarget("?search=hello&q=world")).toBeNull()
  })

  it.each([
    ["?doc=abc123", "/library?doc=abc123"],
    ["?section_id=s1", "/library?section_id=s1"],
    ["?chunk_id=c1", "/library?chunk_id=c1"],
    ["?page=42", "/library?page=42"],
    ["?tag=algebra", "/library?tag=algebra"],
  ])("forwards %s to %s", (search, expected) => {
    expect(getHomeRedirectTarget(search)).toBe(expected)
  })

  it("preserves multi-param query strings", () => {
    expect(getHomeRedirectTarget("?doc=abc&section_id=s1&page=4")).toBe(
      "/library?doc=abc&section_id=s1&page=4",
    )
  })

  it("preserves unrelated params alongside legacy params", () => {
    expect(getHomeRedirectTarget("?doc=abc&search=foo")).toBe("/library?doc=abc&search=foo")
  })

  it("accepts search strings without a leading question mark", () => {
    expect(getHomeRedirectTarget("doc=abc")).toBe("/library?doc=abc")
  })
})
