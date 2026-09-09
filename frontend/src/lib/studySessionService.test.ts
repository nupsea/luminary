import { describe, it, expect, beforeEach, vi } from "vitest"

// Mock studyApi before importing the service. The service imports from
// `@/lib/studyApi`; we replace those exports with mocks so the test does no
// real network I/O.
const mocks = {
  fetchDueCards: vi.fn(),
  fetchOpenSession: vi.fn(),
  fetchSessionRemainingCards: vi.fn(),
  fetchSessionTeachbackResults: vi.fn(),
  reopenSession: vi.fn(),
  endSession: vi.fn(),
  startSession: vi.fn(),
}

vi.mock("@/lib/studyApi", () => ({
  fetchDueCards: (...args: unknown[]) => mocks.fetchDueCards(...args),
  fetchOpenSession: (...args: unknown[]) => mocks.fetchOpenSession(...args),
  fetchSessionRemainingCards: (...args: unknown[]) =>
    mocks.fetchSessionRemainingCards(...args),
  fetchSessionTeachbackResults: (...args: unknown[]) =>
    mocks.fetchSessionTeachbackResults(...args),
  reopenSession: (...args: unknown[]) => mocks.reopenSession(...args),
  endSession: (...args: unknown[]) => mocks.endSession(...args),
  startSession: (...args: unknown[]) => mocks.startSession(...args),
}))

const { prepareStudySession, endOpenSessionsForScope } = await import(
  "./studySessionService",
)

const scope = {
  mode: "teachback" as const,
  documentId: "doc-1",
  collectionId: null,
  cardLimit: 10,
}

function resetMocks() {
  for (const fn of Object.values(mocks)) fn.mockReset()
  mocks.reopenSession.mockResolvedValue(undefined)
  mocks.endSession.mockResolvedValue(undefined)
  mocks.fetchSessionTeachbackResults.mockResolvedValue([])
}

describe("prepareStudySession -- invariant: one user action = one session", () => {
  beforeEach(() => resetMocks())

  it("creates exactly one session when no open session exists", async () => {
    mocks.fetchOpenSession.mockResolvedValue(null)
    mocks.fetchDueCards.mockResolvedValue([
      { id: "a" },
      { id: "b" },
    ])
    mocks.startSession.mockResolvedValue("new-sid")

    const outcome = await prepareStudySession(scope)

    expect(mocks.startSession).toHaveBeenCalledTimes(1)
    expect(mocks.startSession).toHaveBeenCalledWith(
      "doc-1",
      "teachback",
      null,
      ["a", "b"],
    )
    expect(outcome).toEqual({
      kind: "studying",
      session: expect.objectContaining({
        id: "new-sid",
        mode: "teachback",
        plannedTotal: 2,
        answeredCount: 0,
        documentId: "doc-1",
      }),
    })
  })

  it("returns empty and does not create a session when no cards are due", async () => {
    mocks.fetchOpenSession.mockResolvedValue(null)
    mocks.fetchDueCards.mockResolvedValue([])

    const outcome = await prepareStudySession(scope)

    expect(outcome).toEqual({ kind: "empty" })
    expect(mocks.startSession).not.toHaveBeenCalled()
  })

  it("adopts an open session with remaining work instead of creating a new one", async () => {
    mocks.fetchOpenSession.mockResolvedValue({ id: "open-sid" })
    mocks.fetchSessionTeachbackResults.mockResolvedValue([])
    mocks.fetchSessionRemainingCards.mockResolvedValue({
      answered_count: 2,
      planned_count: 5,
      cards: [{ id: "c" }, { id: "d" }, { id: "e" }],
    })

    const outcome = await prepareStudySession(scope)

    expect(mocks.reopenSession).toHaveBeenCalledWith("open-sid")
    expect(mocks.startSession).not.toHaveBeenCalled()
    expect(mocks.endSession).not.toHaveBeenCalled()
    expect(outcome.kind).toBe("studying")
    if (outcome.kind !== "studying") throw new Error("unreachable")
    expect(outcome.session.id).toBe("open-sid")
    expect(outcome.session.plannedTotal).toBe(5)
    expect(outcome.session.answeredCount).toBe(2)
  })

  it("counts a re-answered card once when picking a run back up", async () => {
    // The reported header: "30 of 15 reviewed". A continuous run holds one
    // teach-back row per ATTEMPT, and this resume path took `prevResults.length`
    // -- 30 rows over 5 cards -- against a planned total of 15.
    mocks.fetchOpenSession.mockResolvedValue({ id: "open-sid" })
    mocks.fetchSessionTeachbackResults.mockResolvedValue([
      { id: "t1", flashcard_id: "a" },
      { id: "t2", flashcard_id: "a" },
      { id: "t3", flashcard_id: "a" },
      { id: "t4", flashcard_id: "b" },
      { id: "t5", flashcard_id: "b" },
    ])
    mocks.fetchSessionRemainingCards.mockResolvedValue({
      answered_count: 2,
      planned_count: 5,
      cards: [{ id: "c" }, { id: "d" }, { id: "e" }],
    })

    const outcome = await prepareStudySession(scope)

    if (outcome.kind !== "studying") throw new Error("unreachable")
    expect(outcome.session.answeredCount).toBe(2)
    expect(outcome.session.answeredCount).toBeLessThanOrEqual(
      outcome.session.plannedTotal,
    )
  })

  it("still counts a result whose card has left the planned set", async () => {
    // Why the max survives: `answered_count` is restricted to the planned ids,
    // so a card answered and then regenerated out of the plan would vanish from
    // the tally if only the backend's number were used.
    mocks.fetchOpenSession.mockResolvedValue({ id: "open-sid" })
    mocks.fetchSessionTeachbackResults.mockResolvedValue([
      { id: "t1", flashcard_id: "gone" },
      { id: "t2", flashcard_id: "a" },
      { id: "t3", flashcard_id: "b" },
    ])
    mocks.fetchSessionRemainingCards.mockResolvedValue({
      answered_count: 2,
      planned_count: 5,
      cards: [{ id: "c" }],
    })

    const outcome = await prepareStudySession(scope)

    if (outcome.kind !== "studying") throw new Error("unreachable")
    expect(outcome.session.answeredCount).toBe(3)
  })

  it("ends a stale empty open session and creates one fresh", async () => {
    mocks.fetchOpenSession.mockResolvedValue({ id: "stale-sid" })
    mocks.fetchSessionTeachbackResults.mockResolvedValue([])
    mocks.fetchSessionRemainingCards.mockResolvedValue({
      answered_count: 0,
      planned_count: 0,
      cards: [],
    })
    mocks.fetchDueCards.mockResolvedValue([{ id: "a" }])
    mocks.startSession.mockResolvedValue("fresh-sid")

    const outcome = await prepareStudySession(scope)

    expect(mocks.endSession).toHaveBeenCalledWith("stale-sid")
    expect(mocks.startSession).toHaveBeenCalledTimes(1)
    expect(outcome).toEqual({
      kind: "studying",
      session: expect.objectContaining({ id: "fresh-sid" }),
    })
  })

  it("adopts an open session that is already complete (has prior work, no remaining)", async () => {
    mocks.fetchOpenSession.mockResolvedValue({ id: "done-sid" })
    mocks.fetchSessionTeachbackResults.mockResolvedValue([])
    mocks.fetchSessionRemainingCards.mockResolvedValue({
      answered_count: 5,
      planned_count: 5,
      cards: [],
    })

    const outcome = await prepareStudySession(scope)

    expect(mocks.endSession).not.toHaveBeenCalled()
    expect(mocks.startSession).not.toHaveBeenCalled()
    expect(outcome.kind).toBe("complete")
    if (outcome.kind !== "complete") throw new Error("unreachable")
    expect(outcome.session.id).toBe("done-sid")
    expect(outcome.session.plannedTotal).toBe(5)
    expect(outcome.session.answeredCount).toBe(5)
  })

  it("closes a STALE session (planned cards deleted, unreviewed) and starts fresh", async () => {
    // The reported bug: a session planned 22 cards, 12 answered, but the
    // remaining planned cards were deleted/regenerated -> 0 live remaining. It
    // must not resurface as a stuck "complete" screen; close it, start fresh.
    mocks.fetchOpenSession.mockResolvedValue({ id: "stale-sid" })
    mocks.fetchSessionTeachbackResults.mockResolvedValue([])
    mocks.fetchSessionRemainingCards.mockResolvedValue({
      answered_count: 12,
      planned_count: 22,
      cards: [],
    })
    mocks.fetchDueCards.mockResolvedValue([{ id: "fresh-card" }])
    mocks.startSession.mockResolvedValue("fresh-sid")

    const outcome = await prepareStudySession(scope)

    expect(mocks.endSession).toHaveBeenCalledWith("stale-sid")
    expect(mocks.startSession).toHaveBeenCalledTimes(1)
    expect(outcome.kind).toBe("studying")
    if (outcome.kind !== "studying") throw new Error("unreachable")
    expect(outcome.session.id).toBe("fresh-sid")
  })

  it("explicit resumeSessionId reattaches even when no work remains", async () => {
    mocks.fetchSessionTeachbackResults.mockResolvedValue([])
    mocks.fetchSessionRemainingCards.mockResolvedValue({
      answered_count: 0,
      planned_count: 0,
      cards: [],
    })

    const outcome = await prepareStudySession({
      ...scope,
      resumeSessionId: "explicit-sid",
    })

    // No fetchOpenSession, no new session. Complete screen state.
    expect(mocks.fetchOpenSession).not.toHaveBeenCalled()
    expect(mocks.startSession).not.toHaveBeenCalled()
    expect(outcome.kind).toBe("complete")
    if (outcome.kind !== "complete") throw new Error("unreachable")
    expect(outcome.session.id).toBe("explicit-sid")
  })

  it("scope mismatch -- open session for another doc is not returned here", async () => {
    // Simulate the backend only returning a match for the exact scope.
    mocks.fetchOpenSession.mockResolvedValue(null)
    mocks.fetchDueCards.mockResolvedValue([{ id: "a" }])
    mocks.startSession.mockResolvedValue("sid-b")

    await prepareStudySession({ ...scope, documentId: "doc-2" })

    expect(mocks.fetchOpenSession).toHaveBeenCalledWith({
      mode: "teachback",
      documentId: "doc-2",
      collectionId: null,
    })
    expect(mocks.startSession).toHaveBeenCalledTimes(1)
  })
})


describe("a run whose deck was replaced", () => {
  beforeEach(() => resetMocks())

  it("is not offered back as a finished run when nothing of its plan survives", async () => {
    // Every planned card deleted: the server reports an empty plan (I-47), so
    // there is no summary worth showing and no work to resume. Adopting it
    // would put the learner on a complete screen whose only button re-resumes
    // the same dead session.
    mocks.fetchOpenSession.mockResolvedValue({ id: "dead-sid" })
    mocks.fetchSessionRemainingCards.mockResolvedValue({
      answered_count: 0,
      planned_count: 0,
      cards: [],
    })
    mocks.fetchSessionTeachbackResults.mockResolvedValue([
      { id: "r1", flashcard_id: "deleted-card", question: "q" },
    ])
    mocks.fetchDueCards.mockResolvedValue([{ id: "fresh" }])
    mocks.startSession.mockResolvedValue("fresh-sid")

    const outcome = await prepareStudySession(scope)

    expect(mocks.endSession).toHaveBeenCalledWith("dead-sid")
    expect(outcome.kind).toBe("studying")
    if (outcome.kind !== "studying") throw new Error("unreachable")
    expect(outcome.session.id).toBe("fresh-sid")
  })
})

describe("endOpenSessionsForScope", () => {
  beforeEach(() => resetMocks())

  it("closes every open session for the scope, not just the newest", async () => {
    // The reported case: a document held two open teach-back runs. Closing one
    // left the other to be adopted by the panel, carrying a plan of cards the
    // replacement had just deleted -- which is how "7 of 8 reviewed" appeared
    // over a deck of three.
    const open: Record<string, string[]> = {
      teachback: ["tb-1", "tb-2"],
      flashcard: ["fc-1"],
    }
    mocks.fetchOpenSession.mockImplementation(({ mode }: { mode: string }) => {
      const next = open[mode].shift()
      return Promise.resolve(next ? { id: next } : null)
    })

    await endOpenSessionsForScope("doc-1", null)

    expect(mocks.endSession.mock.calls.map((c) => c[0]).sort()).toEqual([
      "fc-1",
      "tb-1",
      "tb-2",
    ])
  })

  it("stops rather than spinning when a session will not close", async () => {
    // endSession swallows its errors, so an unclosable session must not loop.
    mocks.fetchOpenSession.mockResolvedValue({ id: "stuck" })
    mocks.endSession.mockRejectedValue(new Error("nope"))

    await endOpenSessionsForScope("doc-1", null)

    expect(mocks.endSession.mock.calls.length).toBeLessThanOrEqual(20)
  })
})
