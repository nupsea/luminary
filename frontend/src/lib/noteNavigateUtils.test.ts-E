import { describe, expect, it } from "vitest"
import { buildTagNavigateDetail } from "./noteNavigateUtils"

describe("buildTagNavigateDetail", () => {
  it("returns correct shape for a simple tag", () => {
    expect(buildTagNavigateDetail("physics")).toEqual({
      tab: "notes",
      filter: { tag: "physics" },
    })
  })

  it("returns correct shape for a hierarchical tag", () => {
    expect(buildTagNavigateDetail("physics/quantum")).toEqual({
      tab: "notes",
      filter: { tag: "physics/quantum" },
    })
  })

  it("preserves tag path with multiple levels", () => {
    expect(buildTagNavigateDetail("a/b/c")).toEqual({
      tab: "notes",
      filter: { tag: "a/b/c" },
    })
  })
})
