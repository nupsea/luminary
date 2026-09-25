import { describe, expect, it } from "vitest"

import { emailUrl } from "./problemReport"

const log = Array.from({ length: 400 }, (_, n) => `2026-09-25 [ollama] line ${n}`).join("\n")
const text = `What happened: Chat model download failed\n\nversion   0.13.2\n\nRecent log:\n${log}`

describe("report email", () => {
  it("fit a mailto: Windows will open, keeping the newest log lines", () => {
    const url = emailUrl("dev@example.org", "Chat model download failed", text)
    expect(url.length).toBeLessThanOrEqual(1900)
    const body = decodeURIComponent(url.split("&body=")[1])
    expect(body).toContain("What happened: Chat model download failed")
    expect(body).toContain("line 399")
    expect(body).not.toContain("line 0\n")
    expect(body).toContain("full report is on your clipboard")
  })

  it("keep the whole log when it fits", () => {
    const short = "What happened: x\n\nRecent log:\na\nb"
    const body = decodeURIComponent(emailUrl("d@e.org", "x", short).split("&body=")[1])
    expect(body).toContain("a\nb")
    expect(body).not.toContain("clipboard")
  })
})
