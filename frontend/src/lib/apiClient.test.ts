import { describe, expect, it } from "vitest"

import { ApiError, ComponentsRequiredError, detailFromError } from "./apiClient"

function apiError(detail: unknown, status = 503): ApiError {
  return new ApiError(status, "Service Unavailable", JSON.stringify({ detail }))
}

describe("detailFromError", () => {
  it("uses a string detail", () => {
    expect(detailFromError(apiError("no such document", 404), "fallback").message).toBe(
      "no such document",
    )
  })

  it("carries components from a structured detail", () => {
    // The regression this guards: `detail` became an object, and the old code
    // only understood strings -- so a message naming exactly what to install
    // was discarded and the user saw the bare fallback instead.
    const err = detailFromError(
      apiError({
        message: "YouTube needs Speech to text and Audio and video support.",
        components: ["transcription", "ffmpeg"],
      }),
      "Upload failed",
    )
    expect(err).toBeInstanceOf(ComponentsRequiredError)
    expect(err.message).toContain("Speech to text")
    expect((err as ComponentsRequiredError).components).toEqual(["transcription", "ffmpeg"])
  })

  it("keeps a structured message even with no components", () => {
    const err = detailFromError(apiError({ message: "something specific" }), "Upload failed")
    expect(err).not.toBeInstanceOf(ComponentsRequiredError)
    expect(err.message).toBe("something specific")
  })

  it("falls back when the detail carries nothing usable", () => {
    expect(detailFromError(apiError({}), "Upload failed").message).toBe("Upload failed")
    expect(detailFromError(new Error("boom"), "Upload failed").message).toBe("boom")
  })
})
