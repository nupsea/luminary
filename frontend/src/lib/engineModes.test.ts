// One definition of the three modes, and a host notice built from what does not run.

import { describe, expect, it } from "vitest"

import {
  ENGINE_MODES,
  engineMode,
  hostNotice,
  localModelNotice,
  modelUnavailableMessage,
  splitNotice,
  type HostVerdict,
} from "./engineModes"
import type { RoutingResponse, WorkRoutingItem } from "./llmRouting"

const UNSUPPORTED: HostVerdict = { supported: false, host: "Linux/x86_64", message: "fallback" }

function row(id: string, label: string, refused: boolean): WorkRoutingItem {
  return {
    id,
    label,
    model: `ollama/${id}`,
    on_device: true,
    routable: true,
    why: "",
    fallback_reason: null,
    refused_reason: refused ? "not run" : null,
  }
}

function routing(mode: string, work: WorkRoutingItem[]): RoutingResponse {
  return { mode, provider: "openai", work, leaves_device: [] }
}

describe("ENGINE_MODES", () => {
  it("defines exactly the three stored values, each with a distinct label", () => {
    expect(ENGINE_MODES.map((m) => m.id)).toEqual(["private", "hybrid", "cloud"])
    expect(new Set(ENGINE_MODES.map((m) => m.label)).size).toBe(3)
  })

  it("says Cloud sends document sections, which Hybrid never does", () => {
    expect(engineMode("cloud").sends).toContain("sections of your documents")
    expect(engineMode("hybrid").sends).not.toContain("documents")
  })

  it("recommends Hybrid, and only Hybrid, for Ask and Practice", () => {
    const recommended = ENGINE_MODES.filter((m) => m.recommendation)
    expect(recommended.map((m) => m.id)).toEqual(["hybrid"])
    expect(engineMode("hybrid").recommendation).toMatch(/Ask and Practice/)
  })

  it("falls back to Local for a value it does not know", () => {
    expect(engineMode(undefined).id).toBe("private")
  })
})

describe("modelUnavailableMessage", () => {
  it("keeps the server's message", () => {
    expect(modelUnavailableMessage("This system isn't supported")).toBe("This system isn't supported")
  })

  it("never tells the user to start Ollama when the server said nothing", () => {
    expect(modelUnavailableMessage(undefined)).not.toContain("ollama")
    expect(modelUnavailableMessage("   ")).toContain("Settings")
  })
})

describe("hostNotice", () => {
  it("says nothing on a supported host", () => {
    expect(hostNotice({ supported: true, host: "Darwin/arm64", message: null }, undefined)).toBeNull()
  })

  it("uses the server message until the routing report arrives", () => {
    expect(hostNotice(UNSUPPORTED, undefined)).toBe("fallback")
  })

  it("names the refused rows and the mode that would run them", () => {
    const text = hostNotice(
      UNSUPPORTED,
      routing("hybrid", [
        row("enrichment", "Summaries, tags and titles at ingest", true),
        row("answering", "Answering your question", false),
      ]),
    )
    expect(text).toContain("In Hybrid mode, not run: summaries, tags and titles at ingest.")
    expect(text).not.toContain("answering your question")
    expect(text).toContain("Cloud mode")
  })

  it("offers no other mode when the saved one already runs everything it can", () => {
    const text = hostNotice(UNSUPPORTED, routing("cloud", [row("figures", "Reading figures", true)]))
    expect(text).toContain("In Cloud mode, not run: reading figures.")
    expect(text).not.toContain("change it in Settings")
  })

  it("disappears when nothing is refused", () => {
    expect(hostNotice(UNSUPPORTED, routing("cloud", [row("answering", "Answering", false)]))).toBeNull()
  })
})

describe("splitNotice", () => {
  const split = (share: number | null): HostVerdict => ({
    supported: true,
    host: "Windows/AMD64, 62% of the model on the graphics card",
    message: null,
    gpu_share: share,
  })
  const work = [
    row("answering", "Answering your question", false),
    { ...row("figures", "Reading figures", false), on_device: false },
  ]

  it("names the measured split, what is slowed, and what Cloud mode costs", () => {
    const text = splitNotice(split(0.627), routing("private", work))
    expect(text).toContain("62% of it runs on the card and the rest on the processor")
    expect(text).toContain("so answering your question will be slower")
    expect(text).not.toContain("reading figures")
    expect(text).toContain("Cloud mode is faster")
    expect(text).toContain("your provider charges for each request")
  })

  it("says nothing when the whole model is on the card, or none of it is measured", () => {
    expect(splitNotice(split(1), routing("private", work))).toBeNull()
    expect(splitNotice(split(null), routing("private", work))).toBeNull()
  })

  it("leaves a model on the processor to the refusal, not to this notice", () => {
    const refused = { ...split(0), supported: false }
    expect(splitNotice(refused, routing("private", work))).toBeNull()
  })

  it("says nothing in Cloud mode, which already runs this work with the key", () => {
    expect(splitNotice(split(0.5), routing("cloud", work))).toBeNull()
  })

  it("waits for the routing report rather than guess what runs here", () => {
    expect(splitNotice(split(0.5), undefined)).toBeNull()
  })
})

describe("localModelNotice", () => {
  const refused: HostVerdict = { supported: false, host: "Linux/x86_64", message: "no" }
  const supported: HostVerdict = { supported: true, host: "Darwin/arm64", message: null }
  const missing = { mode: "private", processing_mode: "unavailable", ollama_reachable: true }

  it("offers the model download on a supported host with no model", () => {
    expect(localModelNotice(missing, supported)).toBe("model-missing")
  })

  it("offers nothing on a refused host: the host notice names the cause", () => {
    expect(localModelNotice(missing, refused)).toBeNull()
    expect(localModelNotice({ ...missing, ollama_reachable: false }, refused)).toBeNull()
  })

  it("says the server is down when Ollama is unreachable", () => {
    expect(localModelNotice({ ...missing, ollama_reachable: false }, supported)).toBe("server-down")
  })

  it("stays quiet outside Local mode or while the verdict is loading into a working state", () => {
    expect(localModelNotice({ ...missing, mode: "cloud" }, supported)).toBeNull()
    expect(localModelNotice({ mode: "private", processing_mode: "local" }, undefined)).toBeNull()
  })
})
