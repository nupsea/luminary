import { describe, expect, it } from "vitest"

import type { Rating } from "@/lib/studyApi"
import {
  PREDICTIONS,
  RATING_CLASS,
  RATING_LABELS,
  RATING_ORDER,
  calibrationMessage,
  getSessionPhase,
  ratingBucket,
} from "@/lib/recallFeedback"

const ALL: Rating[] = ["again", "hard", "good", "easy"]

describe("ratingBucket", () => {
  it("folds the 4-point grade onto the 3 points a learner can predict", () => {
    expect(ALL.map(ratingBucket)).toEqual(["blank", "unsure", "knew", "knew"])
  })
})

describe("calibrationMessage", () => {
  it("calls a prediction calibrated only when it lands in the graded bucket", () => {
    // "good" predicted, "easy" graded is the case that makes the bucket fold
    // load-bearing: two different FSRS grades, one honest prediction.
    expect(calibrationMessage("good", "easy").calibrated).toBe(true)
    expect(calibrationMessage("good", "good").calibrated).toBe(true)
    expect(calibrationMessage("again", "again").calibrated).toBe(true)
    expect(calibrationMessage("hard", "hard").calibrated).toBe(true)
  })

  it("names overconfidence when the grade came in below the prediction", () => {
    for (const [p, a] of [["good", "hard"], ["good", "again"], ["hard", "again"]] as const) {
      const cal = calibrationMessage(p, a)
      expect(cal.calibrated, `${p} -> ${a}`).toBe(false)
      expect(cal.tone, `${p} -> ${a}`).toBe("warn")
    }
  })

  it("names underconfidence when the grade came in above the prediction", () => {
    for (const [p, a] of [["again", "hard"], ["again", "good"], ["hard", "easy"]] as const) {
      const cal = calibrationMessage(p, a)
      expect(cal.calibrated, `${p} -> ${a}`).toBe(false)
      expect(cal.tone, `${p} -> ${a}`).toBe("info")
    }
  })

  it("answers for every prediction the UI can produce against every grade", () => {
    for (const p of PREDICTIONS.map((x) => x.value)) {
      for (const a of ALL) {
        const cal = calibrationMessage(p, a)
        expect(cal.text.length, `${p} -> ${a}`).toBeGreaterThan(0)
      }
    }
  })
})

describe("the grade vocabulary", () => {
  it("labels and colours every rating the loop can submit", () => {
    for (const r of RATING_ORDER) {
      expect(RATING_LABELS[r]).toBeTruthy()
      expect(RATING_CLASS[r]).toBeTruthy()
    }
    expect([...RATING_ORDER].sort()).toEqual([...ALL].sort())
  })

  it("predicts on a coarser scale than it grades", () => {
    expect(PREDICTIONS.length).toBeLessThan(RATING_ORDER.length)
  })
})

describe("getSessionPhase", () => {
  it("does not phase a run too short to have phases", () => {
    expect(getSessionPhase(0, 3).label).toBe("Review")
    expect(getSessionPhase(2, 3).label).toBe("Review")
  })

  it("moves warm-up -> engage -> reflect across a real run", () => {
    expect(getSessionPhase(0, 20).label).toBe("Warm-up")
    expect(getSessionPhase(4, 20).label).toBe("Warm-up")
    // 5/20 = 0.25 is the first index past warm-up, and 17/20 = 0.85 the first
    // past engage: both boundaries are exclusive on the lower phase.
    expect(getSessionPhase(5, 20).label).toBe("Engage")
    expect(getSessionPhase(16, 20).label).toBe("Engage")
    expect(getSessionPhase(17, 20).label).toBe("Reflect")
    expect(getSessionPhase(19, 20).label).toBe("Reflect")
  })
})
