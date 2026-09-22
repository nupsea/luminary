// One definition of the three modes, and a host notice built from what does not run.

import { describe, expect, it } from "vitest"

import {
  ENGINE_MODES,
  engineMode,
  hostNotice,
  modelUnavailableMessage,
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
