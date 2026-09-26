import { describe, expect, it } from "vitest"

import {
  engineOfferCopy,
  PROVIDER_SETUP,
  providerSetup,
  shouldOfferEngineChoice,
} from "./engineOffer"

describe("shouldOfferEngineChoice", () => {
  const base = { mode: "private", modeChosen: false, offerDismissed: false }

  it("offers a library whose mode is the default nobody chose", () => {
    expect(shouldOfferEngineChoice(base)).toBe(true)
  })

  it("stays quiet once the question has been answered, even with the same answer", () => {
    expect(shouldOfferEngineChoice({ ...base, modeChosen: true })).toBe(false)
  })

  it("stays quiet after it has been waved away", () => {
    expect(shouldOfferEngineChoice({ ...base, offerDismissed: true })).toBe(false)
  })

  it("has nothing to say to a library already answering in the cloud", () => {
    expect(shouldOfferEngineChoice({ ...base, mode: "hybrid" })).toBe(false)
    expect(shouldOfferEngineChoice({ ...base, mode: "cloud" })).toBe(false)
  })

  it("offers nothing while the settings are still loading", () => {
    expect(shouldOfferEngineChoice(undefined)).toBe(false)
  })
})

describe("engineOfferCopy", () => {
  it("never tells a host that refuses local models its answers are written locally", () => {
    const copy = engineOfferCopy(false)
    expect(copy.title).not.toMatch(/written on this machine/)
    expect(copy.body).toMatch(/can't run a local model/)
    expect(copy.body).toMatch(/Hybrid or Cloud/)
  })

  it("keeps the local-first wording where local models run, or before the host is known", () => {
    for (const supported of [true, undefined]) {
      expect(engineOfferCopy(supported).title).toBe("Answers are being written on this machine")
    }
  })
})

describe("PROVIDER_SETUP", () => {
  it("gives every provider the question offers a place to get a key", () => {
    expect(PROVIDER_SETUP.map((p) => p.id).sort()).toEqual(["anthropic", "gemini", "openai"])
    for (const p of PROVIDER_SETUP) {
      expect(p.consoleUrl.startsWith("https://")).toBe(true)
    }
  })

  it("answers nothing for a provider it does not know", () => {
    expect(providerSetup("mistral")).toBeUndefined()
  })
})
