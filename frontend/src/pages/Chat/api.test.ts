import { describe, it, expect } from "vitest"
import { persistedToChatMessage } from "./api"

const persisted = (extra: Record<string, unknown> | null) => ({
  id: "m1",
  session_id: "s1",
  role: "assistant" as const,
  content: "Once upon a time",
  extra,
  created_at: "2026-10-19T07:11:03",
})

describe("persistedToChatMessage", () => {
  it("restores the repetition stop so the note survives a reload", () => {
    expect(persistedToChatMessage(persisted({ stopped: "repetition" })).stopped).toBe("repetition")
  })

  it("leaves an ordinary answer unflagged", () => {
    expect(persistedToChatMessage(persisted({ confidence: "high" })).stopped).toBeUndefined()
    expect(persistedToChatMessage(persisted(null)).stopped).toBeUndefined()
  })
})
