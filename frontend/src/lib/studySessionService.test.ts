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

const { prepareStudySession } = await import("./studySessionService")

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

