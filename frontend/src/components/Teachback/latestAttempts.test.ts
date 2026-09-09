import { describe, expect, it } from "vitest"

import type { PendingTeachback, TeachbackResultItem } from "@/lib/studyApi"

import { standingAttempts, tallyRun } from "./latestAttempts"

function attempt(id: string, flashcardId: string): PendingTeachback {
  return { id, flashcardId, question: `Q ${flashcardId}` }
}

function verdict(
  id: string,
  flashcardId: string,
  score: number | null,
  status: TeachbackResultItem["status"] = "complete",
): TeachbackResultItem {
  return {
    id,
    status,
    flashcard_id: flashcardId,
    question: `Q ${flashcardId}`,
    score,
    correct_points: [],
    missing_points: [],
    misconceptions: [],
    correction_flashcard_id: null,
    rubric: null,
  }
}

describe("standingAttempts", () => {
  it("keeps one row per card, the latest attempt", () => {
    const standing = standingAttempts([
      attempt("a1", "geometry"),
      attempt("a2", "simplex"),
      attempt("a3", "geometry"),
    ])
    expect(standing.map((s) => s.attempt.id)).toEqual(["a3", "a2"])
  })

  it("counts the attempts so the summary can say a card was re-answered", () => {
    const standing = standingAttempts([
      attempt("a1", "geometry"),
      attempt("a2", "geometry"),
      attempt("a3", "geometry"),
    ])
    expect(standing).toHaveLength(1)
    expect(standing[0].attemptCount).toBe(3)
  })

  it("holds the order in which cards were first met", () => {
    const standing = standingAttempts([
      attempt("a1", "first"),
      attempt("a2", "second"),
      attempt("a3", "first"),
    ])
    expect(standing.map((s) => s.attempt.flashcardId)).toEqual(["first", "second"])
  })
})

describe("tallyRun", () => {
  it("reports the screenshot's run as two cards averaging 68, not three averaging 48", () => {
    const pending = [
      attempt("a1", "geometry"),
      attempt("a2", "simplex"),
      attempt("a3", "geometry"),
    ]
    const results = [
      verdict("a1", "geometry", 10),
      verdict("a2", "simplex", 90),
      verdict("a3", "geometry", 45),
    ]
    expect(tallyRun(pending, results)).toEqual({
      answered: 2,
      scored: 2,
      passed: 1,
      avgScore: 68,
      stillScoring: 0,
    })
  })

  it("reports where the learner ended up, even when that is worse", () => {
    const pending = [attempt("a1", "c1"), attempt("a2", "c1")]
    const results = [verdict("a1", "c1", 90), verdict("a2", "c1", 20)]
    expect(tallyRun(pending, results)).toMatchObject({ answered: 1, passed: 0, avgScore: 20 })
  })

  it("withholds the average while a standing attempt is still scoring", () => {
    const pending = [attempt("a1", "c1"), attempt("a2", "c2")]
    const results = [verdict("a1", "c1", 80), verdict("a2", "c2", null, "pending")]
    expect(tallyRun(pending, results)).toMatchObject({
      answered: 2,
      scored: 1,
      avgScore: null,
      stillScoring: 1,
    })
  })

  it("never reports 0 for a card that has no verdict", () => {
    const pending = [attempt("a1", "c1")]
    expect(tallyRun(pending, undefined).avgScore).toBeNull()
    expect(tallyRun(pending, undefined).scored).toBe(0)
  })

  it("does not wait on an attempt that was superseded", () => {
    const pending = [attempt("a1", "c1"), attempt("a2", "c1")]
    const results = [verdict("a1", "c1", null, "pending"), verdict("a2", "c1", 70)]
    expect(tallyRun(pending, results)).toMatchObject({ avgScore: 70, stillScoring: 0 })
  })

  it("counts a failed submission as answered and not as still scoring", () => {
    const pending = [attempt("error-c1", "c1"), attempt("a2", "c2")]
    const results = [verdict("a2", "c2", 80)]
    expect(tallyRun(pending, results)).toMatchObject({
      answered: 2,
      scored: 1,
      avgScore: 80,
      stillScoring: 0,
    })
  })
})
