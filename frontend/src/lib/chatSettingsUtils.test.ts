import { describe, it, expect } from "vitest"
import {
  buildModelOptions,
  buildTransparencyIconLabel,
  DRAWER_SECTIONS,
  TRANSPARENCY_DEFAULT_OPEN,
} from "./chatSettingsUtils"

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

  it("includes scope selector -- scope moved to drawer", () => {
    expect(DRAWER_SECTIONS).toContain("scope")
  })

  it("includes web_search toggle -- web toggle renders in drawer, not in header", () => {
    expect(DRAWER_SECTIONS).toContain("web_search")
  })
})

describe("TRANSPARENCY_DEFAULT_OPEN", () => {
  it("transparency panel is collapsed by default (false)", () => {
    expect(TRANSPARENCY_DEFAULT_OPEN).toBe(false)
  })
})
