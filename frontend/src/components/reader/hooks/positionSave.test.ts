import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  NOWHERE,
  POSITION_SETTLE_MS,
  placeOfPosition,
  positionBody,
  settledSaver,
  withSaved,
} from "./positionSave"

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe("settledSaver", () => {
  it("saves a section once the reader has stayed on it", () => {
    const save = vi.fn()
    const saver = settledSaver(save)
    saver.reach("ch3")
    vi.advanceTimersByTime(POSITION_SETTLE_MS - 1)
    expect(save).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(save).toHaveBeenCalledWith("ch3")
  })

  it("saves only where the reader settled, not each section scrolled past", () => {
    const save = vi.fn()
    const saver = settledSaver(save)
    saver.reach("ch2")
    vi.advanceTimersByTime(3_000)
    saver.reach("ch3")
    vi.advanceTimersByTime(POSITION_SETTLE_MS)
    expect(save.mock.calls).toEqual([["ch3"]])
  })

  it("does not save the same section twice running", () => {
    const save = vi.fn()
    const saver = settledSaver(save)
    saver.reach("ch3")
    vi.advanceTimersByTime(POSITION_SETTLE_MS)
    saver.reach("ch3")
    vi.advanceTimersByTime(POSITION_SETTLE_MS)
    expect(save).toHaveBeenCalledTimes(1)
  })

  it("going back to the saved section drops the one passed on the way", () => {
    const save = vi.fn()
    const saver = settledSaver(save)
    saver.reach("ch3")
    vi.advanceTimersByTime(POSITION_SETTLE_MS)
    saver.reach("ch4")
    saver.reach("ch3")
    vi.advanceTimersByTime(POSITION_SETTLE_MS)
    expect(save.mock.calls).toEqual([["ch3"]])
  })

  it("saves nothing once stopped", () => {
    const save = vi.fn()
    const saver = settledSaver(save)
    saver.reach("ch3")
    saver.stop()
    vi.advanceTimersByTime(POSITION_SETTLE_MS)
    expect(save).not.toHaveBeenCalled()
  })
})

describe("the saved position", () => {
  const saved = placeOfPosition({
    document_id: "d1",
    last_section_id: "s7",
    last_section_heading: "Chapter 7",
    last_pdf_page: null,
    last_epub_chapter_index: 4,
    last_epub_block_index: 31,
    pdf_bookmark_page: null,
  })

  it("keeps the saved section when only the book's place was read", () => {
    const read = { ...NOWHERE, epubPlace: { chapter: 5, block: 2 }, heading: "Chapter 8" }
    expect(positionBody(withSaved(read, saved))).toEqual({
      last_section_id: "s7",
      last_section_heading: "Chapter 8",
      last_pdf_page: null,
      last_epub_chapter_index: 5,
      last_epub_block_index: 2,
    })
  })

  it("is saved unchanged when nothing was read", () => {
    expect(positionBody(withSaved(NOWHERE, saved))).toEqual(positionBody(saved))
  })

  it("reads a chapter saved without a block as the chapter's start", () => {
    const pos = { document_id: "d1", last_section_id: null, last_section_heading: null, last_pdf_page: null,
      last_epub_chapter_index: 2, last_epub_block_index: null, pdf_bookmark_page: null }
    expect(placeOfPosition(pos).epubPlace).toEqual({ chapter: 2, block: 0 })
  })
})
