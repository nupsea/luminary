import { describe, it, expect } from "vitest"
import {
  isDocumentReady,
  isDocumentProcessing,
  isDocumentErrored,
} from "./documentReadiness"

describe("documentReadiness", () => {
  it("treats stage === 'complete' as ready", () => {
    expect(isDocumentReady({ stage: "complete" })).toBe(true)
    expect(isDocumentReady({ stage: "embedding" })).toBe(false)
    expect(isDocumentReady({ stage: "error" })).toBe(false)
  })

  it("treats null/undefined as not ready and not processing", () => {
    expect(isDocumentReady(null)).toBe(false)
    expect(isDocumentReady(undefined)).toBe(false)
    expect(isDocumentProcessing(null)).toBe(false)
    expect(isDocumentErrored(undefined)).toBe(false)
  })

  it("flags any non-terminal stage as processing", () => {
    expect(isDocumentProcessing({ stage: "parsing" })).toBe(true)
    expect(isDocumentProcessing({ stage: "embedding" })).toBe(true)
    expect(isDocumentProcessing({ stage: "complete" })).toBe(false)
    expect(isDocumentProcessing({ stage: "error" })).toBe(false)
  })

  it("flags stage === 'error' as errored", () => {
    expect(isDocumentErrored({ stage: "error" })).toBe(true)
    expect(isDocumentErrored({ stage: "complete" })).toBe(false)
  })
})
