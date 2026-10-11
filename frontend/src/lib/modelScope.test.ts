import { describe, expect, it } from "vitest"

import { modelScopeCopy } from "./modelScope"

describe("modelScopeCopy", () => {
  it("names the model Auto resolves to", () => {
    const copy = modelScopeCopy("chat", "", "gemini/gemini-3.5-flash-lite")
    expect(copy.status).toBe("Auto follows Settings, which uses gemini-3.5-flash-lite now.")
  })

  it("says a pin holds until Auto is chosen", () => {
    const copy = modelScopeCopy("chat", "ollama/qwen3.5:4b", "gemini/gemini-3.5-flash-lite")
    expect(copy.status).toContain("Pinned to qwen3.5:4b")
    expect(copy.status).toContain("Choose Auto")
  })

  it("tells Ask's stored choice apart from a surface's passing one", () => {
    expect(modelScopeCopy("chat", "", "m").affects).toContain("after you reopen it")
    expect(modelScopeCopy("study", "", "m").affects).toContain("until you leave it")
  })

  it("never claims to change Settings or background work", () => {
    for (const surface of ["chat", "study", "practice", "blog"] as const) {
      const { leaves } = modelScopeCopy(surface, "", "m")
      expect(leaves).toMatch(/^Settings/)
      expect(leaves).toContain("summaries and tags")
    }
  })
})
