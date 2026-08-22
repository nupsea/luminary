import { describe, expect, it } from "vitest"

import { classifyPollFailure } from "./ingestionTrackerCore"

const MAX = 6

describe("classifyPollFailure", () => {
  it("drops a job whose document was deleted", () => {
    // The shipped bug: every rejected poll was skipped, so a document deleted
    // mid-ingestion 404ed on every tick and its job stayed "processing"
    // forever. The progress pill sat at the stage it had reached -- "Summarising
    // sections 38s" -- with nothing able to clear it.
    expect(classifyPollFailure(404, 0, MAX)).toEqual({ action: "drop" })
    // Still gone however many polls have already failed.
    expect(classifyPollFailure(404, MAX - 1, MAX)).toEqual({ action: "drop" })
  })

  it("retries a transient failure rather than dropping the job", () => {
    // A restarting backend or a dropped connection is not a deleted document,
    // and treating it as one would lose a job that is still running.
    expect(classifyPollFailure(503, 0, MAX)).toEqual({ action: "retry", missedPolls: 1 })
    expect(classifyPollFailure(null, 2, MAX)).toEqual({ action: "retry", missedPolls: 3 })
  })

  it("gives up once the status has been unreadable long enough", () => {
    // A job whose status can never be read is not a job in progress, and
    // leaving it polling forever is the same stuck pill by a different route.
    expect(classifyPollFailure(500, MAX - 1, MAX)).toEqual({ action: "give-up" })
    expect(classifyPollFailure(null, MAX, MAX)).toEqual({ action: "give-up" })
  })

  it("counts only consecutive failures, since a success resets the count", () => {
    // The provider writes missedPolls: 0 on every good poll, so reaching the
    // ceiling means the ceiling was reached in a row.
    expect(classifyPollFailure(500, 0, MAX)).toEqual({ action: "retry", missedPolls: 1 })
  })
})
