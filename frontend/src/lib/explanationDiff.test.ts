import { describe, it, expect } from "vitest"
import { computeExplanationDiff, splitSentences } from "./explanationDiff"

describe("splitSentences", () => {
  it("splits on '. ' boundaries", () => {
    const result = splitSentences("The cat sat. The dog ran. The bird flew.")
    expect(result).toEqual(["The cat sat", "The dog ran", "The bird flew"])
  })

  it("returns empty array for empty string", () => {
    expect(splitSentences("")).toEqual([])
  })

  it("handles single sentence with trailing period", () => {
    expect(splitSentences("Hello world.")).toEqual(["Hello world"])
  })
})

describe("computeExplanationDiff", () => {
  it("classifies shared/model_only/user_only for a known 3-sentence pair", () => {
    const user = ["The sky is blue", "Water is wet", "Grass is green"]
    const model = ["The sky is blue", "Fire is hot", "Water is wet"]

    const segments = computeExplanationDiff(user, model)

    // Model sentences in order: shared, model_only, shared
    const modelSegments = segments.filter((s) => s.kind !== "user_only")
    expect(modelSegments[0]).toEqual({ text: "The sky is blue", kind: "shared" })
    expect(modelSegments[1]).toEqual({ text: "Fire is hot", kind: "model_only" })
    expect(modelSegments[2]).toEqual({ text: "Water is wet", kind: "shared" })

    // User-only: Grass is green
    const userOnly = segments.filter((s) => s.kind === "user_only")
    expect(userOnly).toEqual([{ text: "Grass is green", kind: "user_only" }])
  })

  it("returns all shared when sentences match exactly", () => {
    const sentences = ["A is B", "C is D"]
    const segments = computeExplanationDiff(sentences, sentences)
    expect(segments.every((s) => s.kind === "shared")).toBe(true)
    expect(segments).toHaveLength(2)
  })

  it("returns all model_only when user is empty", () => {
    const model = ["Only model", "Another sentence"]
    const segments = computeExplanationDiff([], model)
    expect(segments.every((s) => s.kind === "model_only")).toBe(true)
  })

  it("returns all user_only when model is empty", () => {
    const user = ["Only user", "Another user sentence"]
    const segments = computeExplanationDiff(user, [])
    expect(segments.every((s) => s.kind === "user_only")).toBe(true)
  })

  it("returns empty array for both empty inputs", () => {
    expect(computeExplanationDiff([], [])).toEqual([])
  })

  it("is case-insensitive for matching", () => {
    const user = ["the sky is blue"]
    const model = ["The sky is blue"]
    const segments = computeExplanationDiff(user, model)
    expect(segments[0].kind).toBe("shared")
  })
})
