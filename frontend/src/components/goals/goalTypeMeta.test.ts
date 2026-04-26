import { describe, expect, it } from "vitest"
import {
  defaultTargetUnitForGoalType,
  expectedSurfaceForGoalType,
  progressLabel,
  progressPercent,
  surfaceMismatchWarning,
} from "./goalTypeMeta"

describe("expectedSurfaceForGoalType", () => {
  it("maps read|recall|write|explore to matching surfaces", () => {
    expect(expectedSurfaceForGoalType("read")).toBe("read")
    expect(expectedSurfaceForGoalType("recall")).toBe("recall")
    expect(expectedSurfaceForGoalType("write")).toBe("write")
    expect(expectedSurfaceForGoalType("explore")).toBe("explore")
  })
})

describe("defaultTargetUnitForGoalType", () => {
  it("returns sensible default units", () => {
    expect(defaultTargetUnitForGoalType("read")).toBe("minutes")
    expect(defaultTargetUnitForGoalType("recall")).toBe("cards")
    expect(defaultTargetUnitForGoalType("write")).toBe("notes")
    expect(defaultTargetUnitForGoalType("explore")).toBe("turns")
  })
})

describe("progressLabel", () => {
  it("formats actual / target for a recall goal with a target", () => {
    const out = progressLabel("recall", { cards_reviewed: 12 }, 50, "cards")
    expect(out).toBe("12 / 50 cards")
  })

  it("uses default target_unit if target_unit is null", () => {
    const out = progressLabel("recall", { cards_reviewed: 5 }, 10, null)
    expect(out).toBe("5 / 10 cards")
  })

  it("renders just actual + unit when no target is set", () => {
    const out = progressLabel("read", { minutes_focused: 18 }, null, "minutes")
    expect(out).toBe("18 minutes")
  })

  it("falls back to 0 when the matching metric is absent", () => {
    expect(progressLabel("write", {}, 5, "notes")).toBe("0 / 5 notes")
    expect(progressLabel("explore", {}, null, null)).toBe("0 turns")
  })
})

describe("progressPercent", () => {
  it("clamps to 0..100 and tolerates undefined", () => {
    expect(progressPercent({ completed_pct: 42 })).toBe(42)
    expect(progressPercent({ completed_pct: 150 })).toBe(100)
    expect(progressPercent({ completed_pct: -5 })).toBe(0)
    expect(progressPercent({})).toBe(0)
    expect(progressPercent({ completed_pct: NaN })).toBe(0)
  })
})

describe("surfaceMismatchWarning", () => {
  it("returns null when surfaces agree", () => {
    expect(surfaceMismatchWarning("recall", "recall")).toBeNull()
    expect(surfaceMismatchWarning("read", "read")).toBeNull()
  })

  it("returns null when active surface is none", () => {
    expect(surfaceMismatchWarning("recall", "none")).toBeNull()
  })

  it("returns a string when surfaces disagree", () => {
    const out = surfaceMismatchWarning("recall", "write")
    expect(out).toContain("recall")
    expect(out).toContain("write")
  })
})
