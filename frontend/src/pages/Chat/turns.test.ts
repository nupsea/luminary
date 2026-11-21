import { describe, expect, it } from "vitest"

import { beginTurn, endTurn, isTurnInFlight } from "./turns"

describe("turn in flight", () => {
  it("is per thread and outlives whatever started it", () => {
    beginTurn("doc:a")
    expect(isTurnInFlight("doc:a")).toBe(true)
    expect(isTurnInFlight("doc:b")).toBe(false)
    endTurn("doc:a")
    expect(isTurnInFlight("doc:a")).toBe(false)
  })
})
