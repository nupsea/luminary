import { describe, expect, it } from "vitest"

import { STUDY_PRINCIPLES, principleOfTheDay } from "./studyPrinciples"

describe("principleOfTheDay", () => {
  it("holds for a whole day and moves on the next", () => {
    const morning = principleOfTheDay(new Date(Date.UTC(2026, 7, 3, 6, 0)))
    const evening = principleOfTheDay(new Date(Date.UTC(2026, 7, 3, 23, 0)))
    const tomorrow = principleOfTheDay(new Date(Date.UTC(2026, 7, 4, 6, 0)))

    expect(morning).toBe(evening)
    expect(tomorrow).not.toBe(morning)
  })

  it("always returns a line", () => {
    // Walk a full year; an off-by-one in the day maths would land on undefined.
    for (let day = 0; day < 366; day++) {
      const d = new Date(Date.UTC(2026, 0, 1 + day))
      expect(principleOfTheDay(d)).toBeTruthy()
      expect(STUDY_PRINCIPLES).toContain(principleOfTheDay(d))
    }
  })

  it("shares its source with the boot screen", () => {
    // The Tauri boot screen reads the same JSON before the SPA exists. If this
    // import breaks, the two screens show different lines on the same launch.
    expect(STUDY_PRINCIPLES.length).toBeGreaterThan(5)
    for (const line of STUDY_PRINCIPLES) {
      expect(typeof line).toBe("string")
      expect(line.length).toBeGreaterThan(20)
    }
  })
})
