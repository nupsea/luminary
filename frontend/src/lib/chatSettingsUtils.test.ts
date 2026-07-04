import { describe, it, expect } from "vitest"
import {
  buildModelOptions,
  buildTransparencyIconLabel,
  buildScopeComboboxLabel,
  DRAWER_SECTIONS,
  effectiveDefaultModel,
  shortModelLabel,
  TRANSPARENCY_DEFAULT_OPEN,
} from "./chatSettingsUtils"

describe("effectiveDefaultModel", () => {
  it("uses provider/model in cloud and hybrid mode", () => {
    const base = { active_model: "", available_local_models: [] }
    expect(
      effectiveDefaultModel({ ...base, processing_mode: "hybrid", provider: "openai", model: "gpt-5.1" }),
    ).toBe("openai/gpt-5.1")
    expect(
      effectiveDefaultModel({ ...base, processing_mode: "cloud", provider: "anthropic", model: "claude-sonnet-4-6" }),
    ).toBe("anthropic/claude-sonnet-4-6")
  })

  it("uses the local model in private/local mode", () => {
    expect(
      effectiveDefaultModel({
        processing_mode: "local",
        active_model: "ollama/gemma4:latest",
        available_local_models: ["ollama/gemma4:latest"],
      }),
    ).toBe("ollama/gemma4:latest")
  })

  it("falls back to the first local model when active_model is empty", () => {
    expect(
      effectiveDefaultModel({
        processing_mode: "local",
        active_model: "",
        available_local_models: ["ollama/mistral:latest"],
      }),
    ).toBe("ollama/mistral:latest")
  })

  it("returns empty string when settings are undefined", () => {
    expect(effectiveDefaultModel(undefined)).toBe("")
  })
})

describe("shortModelLabel", () => {
  it("strips the provider prefix", () => {
    expect(shortModelLabel("openai/gpt-5.1")).toBe("gpt-5.1")
    expect(shortModelLabel("ollama/qwen2.5:14b-instruct")).toBe("qwen2.5:14b-instruct")
  })
  it("leaves an unprefixed id unchanged", () => {
    expect(shortModelLabel("gemma4")).toBe("gemma4")
  })
})

describe("buildModelOptions", () => {
  it("returns empty array when settings is undefined", () => {
    expect(buildModelOptions(undefined)).toEqual([])
  })

  it("returns empty array in cloud mode", () => {
    expect(
      buildModelOptions({
        processing_mode: "cloud",
        active_model: "gpt-4",
        available_local_models: [],
      }),
    ).toEqual([])
  })

  it("returns available_local_models in local mode", () => {
    expect(
      buildModelOptions({
        processing_mode: "local",
        active_model: "llama3",
        available_local_models: ["llama3", "mistral"],
      }),
    ).toEqual(["llama3", "mistral"])
  })

  it("returns active_model fallback when no local models listed", () => {
    expect(
      buildModelOptions({
        processing_mode: "local",
        active_model: "llama3",
        available_local_models: [],
      }),
    ).toEqual(["llama3"])
  })

  it("returns empty array when local mode but no active_model or local models", () => {
    expect(
      buildModelOptions({
        processing_mode: "local",
        active_model: "",
        available_local_models: [],
      }),
    ).toEqual([])
  })
})

describe("buildTransparencyIconLabel", () => {
  it("returns High confidence for high", () => {
    expect(buildTransparencyIconLabel("high")).toBe("High confidence")
  })

  it("returns Medium confidence for medium", () => {
    expect(buildTransparencyIconLabel("medium")).toBe("Medium confidence")
  })

  it("returns Low confidence for low", () => {
    expect(buildTransparencyIconLabel("low")).toBe("Low confidence")
  })

  it("returns Unknown confidence for unrecognized input", () => {
    expect(buildTransparencyIconLabel("very_high")).toBe("Unknown confidence")
  })
})

describe("DRAWER_SECTIONS", () => {
  it("includes model selector -- model selector renders in drawer, not in header", () => {
    expect(DRAWER_SECTIONS).toContain("model")
  })

  it("does NOT include scope -- scope moved to inline combobox in Chat header", () => {
    expect(DRAWER_SECTIONS).not.toContain("scope")
  })

  it("includes web_search toggle -- web toggle renders in drawer, not in header", () => {
    expect(DRAWER_SECTIONS).toContain("web_search")
  })
})

describe("buildScopeComboboxLabel", () => {
  it("returns 'All documents' when selectedTitle is null", () => {
    expect(buildScopeComboboxLabel(null)).toBe("All documents")
  })

  it("returns short title as-is", () => {
    expect(buildScopeComboboxLabel("The Odyssey")).toBe("The Odyssey")
  })

  it("truncates long title to 28 chars + ellipsis", () => {
    const long = "A very long document title that exceeds truncation limit"
    const label = buildScopeComboboxLabel(long)
    expect(label).toBe(long.slice(0, 28) + "...")
    expect(label.length).toBe(31) // 28 + 3 for "..."
  })

  it("returns title at exactly 28 chars without truncation", () => {
    const exact = "A".repeat(28)
    expect(buildScopeComboboxLabel(exact)).toBe(exact)
  })

  it("chatPreload pre-selection: shows document title when scope is single", () => {
    // Simulates: chatPreload sets documentId, we look up the title from docList
    const docList = [{ id: "doc-1", title: "Doc One" }, { id: "doc-2", title: "Doc Two" }]
    const preloadDocId = "doc-1"
    const selectedDoc = docList.find((d) => d.id === preloadDocId)
    expect(buildScopeComboboxLabel(selectedDoc?.title ?? null)).toBe("Doc One")
  })
})

describe("TRANSPARENCY_DEFAULT_OPEN", () => {
  it("transparency panel is collapsed by default (false)", () => {
    expect(TRANSPARENCY_DEFAULT_OPEN).toBe(false)
  })
})
