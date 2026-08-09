import { describe, expect, it } from "vitest"
import { parseSpeakerTurns } from "@/components/reader/speakerTurns"

describe("parseSpeakerTurns", () => {
  it("splits a transcript into labelled turns", () => {
    const turns = parseSpeakerTurns(
      "Alice: Can we ship the reader fix this week?\n" +
        "Bob: The schema change landed, so yes.\n" +
        "Carol: I will re-ingest the corpus tonight.",
    )
    expect(turns).toEqual([
      { speaker: "Alice", text: "Can we ship the reader fix this week?" },
      { speaker: "Bob", text: "The schema change landed, so yes." },
      { speaker: "Carol", text: "I will re-ingest the corpus tonight." },
    ])
  })

  it("keeps a wrapped line with the turn above it", () => {
    const turns = parseSpeakerTurns(
      "Alice: The gateway is fine but the rate limiter\nis using a fixed window.\nBob: Agreed.",
    )
    expect(turns?.[0]).toEqual({
      speaker: "Alice",
      text: "The gateway is fine but the rate limiter\nis using a fixed window.",
    })
    expect(turns?.[1].speaker).toBe("Bob")
  })

  it("keeps a leading title as an unlabelled turn rather than dropping it", () => {
    const turns = parseSpeakerTurns(
      "Weekly Engineering Sync\nAlice: Let us begin.\nBob: Ready.",
    )
    expect(turns?.[0]).toEqual({ speaker: "", text: "Weekly Engineering Sync" })
    expect(turns).toHaveLength(3)
  })

  it("returns null for prose, so it renders as ordinary markdown", () => {
    expect(parseSpeakerTurns("Tell me, O Muse, of that ingenious hero who travelled far.")).toBeNull()
  })

  it("does not restyle a section over one incidental colon line", () => {
    // A single "Note: ..." must not turn a chapter into a transcript.
    expect(
      parseSpeakerTurns("Note: this chapter is dense.\nThe argument proceeds in three parts."),
    ).toBeNull()
  })
})

describe("leading metadata", () => {
  it("does not label a transcript's own header lines as speakers", () => {
    const turns = parseSpeakerTurns(
      "Transcript: Weekly Engineering Sync\n" +
        "Date: 2026-01-15\n" +
        "Participants: Alice, Bob\n" +
        "Alice: Let us begin.\n" +
        "Bob: Ready.\n" +
        "Alice: First item.",
    )
    expect(turns?.slice(0, 3)).toEqual([
      { speaker: "", text: "Transcript: Weekly Engineering Sync" },
      { speaker: "", text: "Date: 2026-01-15" },
      { speaker: "", text: "Participants: Alice, Bob" },
    ])
    expect(turns?.slice(3).map((t) => t.speaker)).toEqual(["Alice", "Bob", "Alice"])
  })

  it("keeps a one-turn participant once the dialogue has started", () => {
    const turns = parseSpeakerTurns(
      "Alice: Opening.\nBob: Reply.\nAlice: Next.\nDavid: My only question.",
    )
    expect(turns?.[3]).toEqual({ speaker: "David", text: "My only question." })
  })
})
