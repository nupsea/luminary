import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { Flashcard } from "@/lib/studyApi"
import { useStudySession } from "./useStudySession"

const endSession = vi.fn()
const discardUnusedSession = vi.fn()
vi.mock("@/lib/studyApi", () => ({
  endSession: (...args: unknown[]) => endSession(...args),
  discardUnusedSession: (...args: unknown[]) => discardUnusedSession(...args),
}))
vi.mock("@/lib/studySessionService", () => ({ prepareStudySession: vi.fn() }))
vi.mock("@/store", () => ({ useAppStore: () => ({ setStudySessionId: () => {} }) }))

function hook(answeredCount: number, queue: Flashcard[]) {
  let api!: ReturnType<typeof useStudySession>
  function Harness() {
    api = useStudySession({
      initial: {
        kind: "studying",
        session: {
          id: "s1",
          mode: "flashcard",
          queue,
          prevResults: [],
          answeredCount,
          plannedTotal: answeredCount + queue.length,
          documentId: "doc-1",
          collectionId: null,
        },
      },
      scopeForBeginNew: { mode: "flashcard", cardLimit: 10 },
    })
    return null
  }
  renderToStaticMarkup(<Harness />)
  return api
}

const card = { id: "c1" } as Flashcard

beforeEach(() => {
  endSession.mockReset().mockResolvedValue(undefined)
  discardUnusedSession.mockReset().mockResolvedValue(undefined)
})

describe("useStudySession exit", () => {
  it("discards a run left without an answer", async () => {
    const onExit = vi.fn()
    await hook(0, [card]).exit(onExit)
    expect(discardUnusedSession).toHaveBeenCalledWith("s1")
    expect(endSession).not.toHaveBeenCalled()
    expect(onExit).toHaveBeenCalledOnce()
  })

  it("keeps a run with progress open for the next Start", async () => {
    await hook(2, [card]).exit(() => {})
    expect(discardUnusedSession).not.toHaveBeenCalled()
    expect(endSession).not.toHaveBeenCalled()
  })
})
