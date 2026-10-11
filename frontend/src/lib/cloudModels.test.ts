import { describe, expect, it } from "vitest"

import {
  formatModelOption,
  hasKeyFor,
  isLocalModel,
  localChatModelHint,
  localChatModelUse,
  modelForProvider,
  saveBlocker,
} from "./cloudModels"

describe("isLocalModel", () => {
  it("keeps a cloud model away from the local installer", () => {
    expect(isLocalModel("ollama/qwen3.5:4b")).toBe(true)
    expect(isLocalModel("qwen3.5:4b")).toBe(true)
    expect(isLocalModel("gemini/gemini-3.5-flash-lite")).toBe(false)
  })
})

describe("localChatModelUse", () => {
  it("says what the local model is in use for, not just that it is", () => {
    expect(localChatModelUse("private").badge).toBe("In use")
    expect(localChatModelUse("hybrid").badge).toBe("In use for summaries, tags and titles")
    expect(localChatModelUse("cloud").badge).toBe("Offline fallback")
  })
})

describe("localChatModelHint", () => {
  it("does not claim the local model answers questions in Hybrid or Cloud", () => {
    expect(localChatModelHint("private", "Google Gemini")).toContain("Answers questions")
    expect(localChatModelHint("hybrid", "Google Gemini")).toContain("Answers and cards use Google Gemini")
    expect(localChatModelHint("cloud", "Google Gemini")).toContain("only when Google Gemini can't be reached")
  })
})

const GEMINI = [
  { id: "gemini-3.8-flash", name: "Gemini 3.8 Flash", recommended: true },
  { id: "gemini-3.1-pro-preview", name: "Gemini 3.1 Pro", cost_note: "preview" },
]

describe("modelForProvider", () => {
  it("does not carry another provider's model into the field", () => {
    expect(modelForProvider(GEMINI, "gpt-4o-mini")).toBe("gemini-3.8-flash")
  })

  it("keeps a model the provider still offers", () => {
    expect(modelForProvider(GEMINI, "gemini-3.1-pro-preview")).toBe("gemini-3.1-pro-preview")
  })

  it("falls back to the first model when none is recommended, and to nothing on an empty list", () => {
    expect(modelForProvider([{ id: "a", name: "A" }], "x")).toBe("a")
    expect(modelForProvider([], "x")).toBe("")
  })
})

describe("hasKeyFor", () => {
  const flags = { has_openai_key: true, has_anthropic_key: false, has_google_key: false }

  it("reads the selected provider's key, not any key", () => {
    expect(hasKeyFor("openai", flags)).toBe(true)
    expect(hasKeyFor("gemini", flags)).toBe(false)
    expect(hasKeyFor("gemini", undefined)).toBe(false)
  })
})

describe("saveBlocker", () => {
  const base = { mode: "hybrid", providerLabel: "Google Gemini", hasKey: false, pendingKey: false, model: "m" }

  it("asks for the provider's key before anything else", () => {
    expect(saveBlocker(base)).toBe("Add a Google Gemini API key first.")
  })

  it("lets a key typed but not yet checked through, since Save checks it", () => {
    expect(saveBlocker({ ...base, pendingKey: true })).toBeNull()
  })

  it("needs a model once there is a key", () => {
    expect(saveBlocker({ ...base, hasKey: true, model: " " })).toBe("Choose a model.")
  })

  it("never blocks Local", () => {
    expect(saveBlocker({ ...base, mode: "private", model: "" })).toBeNull()
  })
})

describe("formatModelOption", () => {
  it("shows a price only when one is known", () => {
    expect(formatModelOption({ id: "a", name: "A", cost_input: null, cost_output: null })).toBe("A")
    expect(formatModelOption({ id: "a", name: "A", cost_input: 1, cost_output: 5 })).toBe(
      "A · $1 / $5 per 1M tokens",
    )
    expect(formatModelOption(GEMINI[0])).toBe("Gemini 3.8 Flash · recommended")
  })
})
