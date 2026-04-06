/**
 * Vitest unit tests for naming convention normalizers (S199).
 * Node environment -- tests pure utility functions from tagUtils.ts.
 */

import { describe, expect, it } from "vitest"
import { normalizeCollectionName, normalizeTagSlug } from "./tagUtils"

describe("normalizeCollectionName", () => {
  it("converts spaces to hyphens and uppercases", () => {
    expect(normalizeCollectionName("my notes")).toBe("MY-NOTES")
  })

  it("converts underscores to hyphens", () => {
    expect(normalizeCollectionName("machine_learning")).toBe("MACHINE-LEARNING")
  })

  it("strips whitespace and collapses", () => {
    expect(normalizeCollectionName("  DDIA  Book  ")).toBe("DDIA-BOOK")
  })

  it("returns empty for empty string", () => {
    expect(normalizeCollectionName("")).toBe("")
  })

  it("strips leading/trailing hyphens", () => {
    expect(normalizeCollectionName("--hello--world--")).toBe("HELLO-WORLD")
  })

  it("handles already normalized input", () => {
    expect(normalizeCollectionName("MY-NOTES")).toBe("MY-NOTES")
  })
})

describe("normalizeTagSlug", () => {
  it("lowercases hierarchy segments", () => {
    expect(normalizeTagSlug("Science/Biology")).toBe("science/biology")
  })

  it("converts spaces to hyphens", () => {
    expect(normalizeTagSlug("Machine Learning")).toBe("machine-learning")
  })

  it("handles underscores in hierarchy", () => {
    expect(normalizeTagSlug("science/Cell_Division")).toBe("science/cell-division")
  })

  it("returns empty for empty string", () => {
    expect(normalizeTagSlug("")).toBe("")
  })

  it("preserves hierarchy separators", () => {
    expect(normalizeTagSlug("a/b/c")).toBe("a/b/c")
  })

  it("strips trailing slash", () => {
    expect(normalizeTagSlug("science/")).toBe("science")
  })

  it("handles already normalized input", () => {
    expect(normalizeTagSlug("machine-learning")).toBe("machine-learning")
  })
})
