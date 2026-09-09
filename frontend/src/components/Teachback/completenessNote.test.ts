import { describe, expect, it } from "vitest"

import { completenessNote } from "./latestAttempts"

describe("completenessNote", () => {
  it("names what was missed when the evaluator named it", () => {
    expect(completenessNote({ score: 40, missed_points: ["event replay", "eventual consistency"] }))
      .toBe("Missed: event replay; eventual consistency")
  })

  it("only claims nothing was left out when the score says so", () => {
    expect(completenessNote({ score: 90, missed_points: [] })).toContain("Nothing the question")
  })

  // The screenshot that started this: "Nothing material was left out." printed
  // beside Completeness 5/100. The sentence read off an empty list, the number
  // came from the model, and the two were never reconciled.
  it("does not tell a learner nothing was missing while scoring them 5", () => {
    const note = completenessNote({ score: 5, missed_points: [] })
    expect(note).not.toContain("Nothing")
    expect(note).toContain("named nothing that was missing")
  })
})
