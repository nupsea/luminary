import { describe, expect, it } from "vitest"

import {
  acceptedExtensions,
  carriesFiles,
  describeRejection,
  detectContentType,
  makeDragDepth,
} from "./uploadFileTypes"

const ALL = { canAudio: true, canVideo: true }
const TEXT_ONLY = { canAudio: false, canVideo: false }

describe("acceptedExtensions", () => {
  it("offers media only when the components that read it are installed", () => {
    expect(acceptedExtensions(ALL)).toContain(".mp3")
    expect(acceptedExtensions(ALL)).toContain(".mp4")
    expect(acceptedExtensions(TEXT_ONLY)).not.toContain(".mp3")
    expect(acceptedExtensions(TEXT_ONLY)).toContain(".pdf")
  })
})

describe("describeRejection", () => {
  it("accepts what the install can read", () => {
    expect(describeRejection("paper.pdf", TEXT_ONLY)).toBeNull()
    expect(describeRejection("Notes.MD", TEXT_ONLY)).toBeNull()
    expect(describeRejection("talk.mp3", ALL)).toBeNull()
  })

  it("names the missing component for a supported-but-uninstalled format", () => {
    // The reported symptom: dropping an MP3 did nothing at all.
    const r = describeRejection("talk.mp3", TEXT_ONLY)
    expect(r?.componentId).toBe("transcription")
    expect(r?.message).toMatch(/speech-to-text/i)
  })

  it("explains an unsupported format instead of staying silent", () => {
    const r = describeRejection("sheet.xlsx", ALL)
    expect(r).not.toBeNull()
    expect(r?.componentId).toBeUndefined()
    expect(r?.message).toContain(".xlsx")
  })

  it("handles a file with no extension", () => {
    expect(describeRejection("README", ALL)).not.toBeNull()
  })
})

describe("detectContentType", () => {
  it("reads the format off the name", () => {
    expect(detectContentType("novel.epub")).toBe("book")
    expect(detectContentType("lecture.M4A")).toBe("audio")
    expect(detectContentType("screencast.mp4")).toBe("video")
    expect(detectContentType("paper.pdf")).toBe("book")
  })
})

describe("makeDragDepth", () => {
  it("stays active while nested children fire their own enter/leave pairs", () => {
    const d = makeDragDepth()
    expect(d.enter()).toBe(true) // window
    expect(d.enter()).toBe(true) // a child under the cursor
    expect(d.leave()).toBe(true) // that child, still inside the window
    expect(d.leave()).toBe(false) // left for real
  })

  it("resets on drop so the next drag starts clean", () => {
    const d = makeDragDepth()
    d.enter()
    d.enter()
    d.reset()
    expect(d.depth).toBe(0)
    expect(d.enter()).toBe(true)
    expect(d.leave()).toBe(false)
  })
})

describe("carriesFiles", () => {
  it("distinguishes a file drag from a text or internal drag", () => {
    expect(carriesFiles(["Files"])).toBe(true)
    expect(carriesFiles(["text/plain"])).toBe(false)
    expect(carriesFiles([])).toBe(false)
    expect(carriesFiles(undefined)).toBe(false)
  })
})
