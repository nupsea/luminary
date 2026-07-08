import { describe, expect, it } from "vitest"

import { distributeByWeight, distributeCount } from "./studyDistribute"

describe("distributeCount", () => {
  it("splits evenly and always sums to total", () => {
    expect(distributeCount(20, 10)).toEqual(new Array(10).fill(2))
    const r = distributeCount(20, 3)
    expect(r.reduce((a, b) => a + b, 0)).toBe(20)
    expect(r).toEqual([7, 7, 6])
  })

  it("handles edge cases", () => {
    expect(distributeCount(0, 4)).toEqual([0, 0, 0, 0])
    expect(distributeCount(20, 0)).toEqual([])
  })
})

describe("distributeByWeight", () => {
  const sum = (a: number[]) => a.reduce((x, y) => x + y, 0)

  it("always sums to the requested total", () => {
    expect(sum(distributeByWeight(20, [11424, 44, 149, 2, 1]))).toBe(20)
    expect(sum(distributeByWeight(30, [60000, 1000, 500]))).toBe(30)
    expect(sum(distributeByWeight(7, [100, 100, 100]))).toBe(7)
  })

  it("gives a large source the majority but never starves small ones", () => {
    // a book (many chunks) beside small notes: book dominates, notes keep >=1
    const r = distributeByWeight(20, [11424, 44, 149, 2, 1])
    expect(r[0]).toBeGreaterThan(sum(r.slice(1))) // book gets the majority
    expect(Math.min(...r)).toBeGreaterThanOrEqual(1) // no content source starved
  })

  it("never gives a source with zero weight any cards", () => {
    // DDIA-with-word_count-0 regression: a 0-weight source must not consume slots
    const r = distributeByWeight(10, [0, 100, 100])
    expect(r[0]).toBe(0)
    expect(sum(r)).toBe(10)
  })

  it("when there are more sources than the total, the largest win", () => {
    const r = distributeByWeight(5, [9000, 8000, 100, 100, 100, 100])
    expect(sum(r)).toBe(5)
    // the two big sources get the most; the tail tiny sources get nothing
    expect(r[0]).toBeGreaterThanOrEqual(r[2])
    expect(r[1]).toBeGreaterThanOrEqual(r[2])
    expect(r[r.length - 1]).toBe(0)
  })

  it("falls back to an even split when no weights are known", () => {
    expect(distributeByWeight(20, [0, 0, 0, 0])).toEqual([5, 5, 5, 5])
  })
})
