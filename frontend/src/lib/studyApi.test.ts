import { afterEach, describe, expect, it, vi } from "vitest"

// Stub localStorage in node environment before importing studyApi
const localStorageData: Record<string, string> = {}
vi.stubGlobal("localStorage", {
  getItem: vi.fn((key: string) => localStorageData[key] ?? null),
  setItem: vi.fn((key: string, value: string) => { localStorageData[key] = value }),
  removeItem: vi.fn((key: string) => { delete localStorageData[key] }),
  clear: vi.fn(() => { for (const k of Object.keys(localStorageData)) delete localStorageData[k] }),
})

const { fetchSessionCards } = await import("./studyApi")
type SessionCardDetail = import("./studyApi").SessionCardDetail

describe("fetchSessionCards", () => {
  const originalFetch = global.fetch

  afterEach(() => {
    global.fetch = originalFetch
  })

  it("fetches session cards and parses json response", async () => {
    const mockData: SessionCardDetail[] = [
      {
        flashcard_id: "card-1",
        question: "What is A?",
        answer: "A is ...",
        source_excerpt: "Excerpt 1",
        section_heading: "Section 1",
        chunk_id: "chunk-1",
        rating: "good",
        is_correct: true,
        predicted_rating: "good",
        reviewed_at: "2026-09-14T00:00:00Z",
      },
    ]

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockData,
    })

    const result = await fetchSessionCards("session-123")
    expect(result).toEqual(mockData)
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/study/sessions/session-123/cards"),
    )
  })

  it("throws an error when response is not ok", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
    })

    await expect(fetchSessionCards("session-unknown")).rejects.toThrow(
      "Failed to fetch cards for session session-unknown: 404",
    )
  })
})
